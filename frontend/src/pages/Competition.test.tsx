/**
 * The Competition page's honesty rules, at render level.
 *
 * Mirrors `Institutions.test.tsx`/`Portfolio.test.tsx`'s approach: `@/api/competition` is stubbed at
 * the module boundary rather than `fetch`, and fixture factories mirror the wire contract field for
 * field so a drift between this file and `api/competition.ts` shows up as a type error rather than a
 * silently-wrong fixture.
 *
 * What these tests pin, matching the task's definition of done:
 *  - the leaderboard renders rows in rank order, with a pinned SPY row carrying every window's own
 *    benchmark return;
 *  - a `null` metric (`median_excess`/`worst_excess`) renders as an em dash, never `0`/`0.00%`;
 *  - a `provenance_constrained` window is marked, and an ineligible row carries its window count;
 *  - clicking a leaderboard row opens the agent drill-down INLINE under the Leaderboard table (there
 *    is no separate "Card" tab any more), closable with its own button, and an `unrealised: true`
 *    trade is labelled as a mark rather than folded into realised P&L;
 *  - a best-card link on the Summary view opens that same drawer by switching to the Leaderboard
 *    view first, since Summary itself has nowhere to render it;
 *  - submitting the run form calls `createJob` with the selected cards/windows, and a `409` renders
 *    a plain message naming the already-running job;
 *  - a running job renders progress, and once it reports `succeeded` the polling interval is
 *    cleared -- proven with fake timers by asserting no further `job()` calls happen.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type {
  AgentDetailResponse,
  AgentWindowDetail,
  CardSummary,
  CreateJobRequest,
  GateOutcome,
  JobCreated,
  JobStatus,
  LeaderboardResponse,
  LeaderboardRow,
  LibraryResponse,
  NextRoundBriefing,
  Purpose,
  RankBy,
  RoundNarrative,
  RoundSummary,
  SelectionResponse,
  FindingsResponse,
  SelectionSeat,
  TradeDetail,
  WindowBenchmark,
  WindowCatalogueEntry,
} from "@/api/competition";

const roundsMock = vi.fn<() => Promise<{ rounds: RoundSummary[] }>>();
const libraryMock = vi.fn<() => Promise<LibraryResponse>>();
const windowsMock = vi.fn<() => Promise<{ windows: WindowCatalogueEntry[] }>>();
const leaderboardMock =
  vi.fn<(roundId: string, rankBy: RankBy, purpose: Purpose) => Promise<LeaderboardResponse>>();
const agentDetailMock = vi.fn<(roundId: string, agentId: string) => Promise<AgentDetailResponse>>();
const createJobMock = vi.fn<(request: CreateJobRequest) => Promise<JobCreated>>();
const jobMock = vi.fn<(jobId: string) => Promise<JobStatus>>();
const cancelJobMock = vi.fn<(jobId: string) => Promise<JobStatus>>();
const selectionMock = vi.fn<(roundId: string) => Promise<SelectionResponse>>();
const findingsMock = vi.fn<(roundId: string) => Promise<FindingsResponse>>();
const narrativeMock = vi.fn<(roundId: string) => Promise<RoundNarrative>>();
const nextRoundMock = vi.fn<() => Promise<NextRoundBriefing>>();

vi.mock("@/api/competition", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/competition")>();
  return {
    ...actual,
    competitionApi: {
      ...actual.competitionApi,
      rounds: () => roundsMock(),
      library: () => libraryMock(),
      windows: () => windowsMock(),
      leaderboard: (roundId: string, rankBy: RankBy, purpose: Purpose) =>
        leaderboardMock(roundId, rankBy, purpose),
      agentDetail: (roundId: string, agentId: string) => agentDetailMock(roundId, agentId),
      createJob: (request: CreateJobRequest) => createJobMock(request),
      job: (jobId: string) => jobMock(jobId),
      cancelJob: (jobId: string) => cancelJobMock(jobId),
      selection: (roundId: string) => selectionMock(roundId),
      findings: (roundId: string) => findingsMock(roundId),
      narrative: (roundId: string) => narrativeMock(roundId),
      nextRound: () => nextRoundMock(),
    },
  };
});

const { default: Competition } = await import("@/pages/Competition");

// --- fixtures --------------------------------------------------------------------------------------

function roundSummary(overrides: Partial<RoundSummary> = {}): RoundSummary {
  return {
    round_id: "r2-2026-08",
    label: "r2 — Aug 2026",
    windows: ["gfc", "covid", "13f-legal"],
    agents: 22,
    has_report: true,
    has_brief: true,
    // A default fixture must be a round that CAN render. `has_results: false` means the leaderboard
    // endpoint 404s for this round by design, and defaulting a picker onto such a round is the exact
    // defect that blanked this tab -- see `defaultRoundId` in `Competition.tsx`.
    has_results: true,
    has_selection: true,
    sequence: 2,
    ...overrides,
  };
}

function windowBenchmark(overrides: Partial<WindowBenchmark> = {}): WindowBenchmark {
  return {
    window: "gfc",
    sessions: 252,
    benchmark_return: "-0.5623",
    provenance_constrained: false,
    ...overrides,
  };
}

function windowCatalogueEntry(overrides: Partial<WindowCatalogueEntry> = {}): WindowCatalogueEntry {
  return {
    window: "gfc",
    start: "2007-10-01",
    end: "2009-03-01",
    label: "global financial crisis",
    main: true,
    matrix: "r2",
    // `null` matches every pre-round-5 window: a named regime window has a length but not a
    // *designed* horizon. Tests that need a horizon-ladder/bear-supplement fixture override this
    // explicitly (see the horizon-grouping describe block below).
    horizon: null,
    ...overrides,
  };
}

const DEFAULT_WINDOW_CATALOGUE: WindowCatalogueEntry[] = [
  windowCatalogueEntry({ window: "gfc", start: "2007-10-01", end: "2009-03-01", main: true }),
  windowCatalogueEntry({
    window: "covid",
    start: "2020-02-19",
    end: "2020-04-07",
    label: "covid crash and recovery",
    main: true,
  }),
  windowCatalogueEntry({
    window: "13f-legal",
    start: "2025-11-17",
    end: "2026-08-18",
    label: "13F-legal window",
    main: false,
  }),
];

function leaderboardRow(overrides: Partial<LeaderboardRow> = {}): LeaderboardRow {
  return {
    rank: 1,
    agent_id: "c07-chop",
    display_name: "Chop Specialist",
    discipline: "mean-reversion",
    windows_run: 1,
    eligible: true,
    median_excess: "0.0272",
    worst_excess: "-0.1003",
    hit_rate: 0.75,
    mean_capital_exposure: 0.41,
    total_trades: 109,
    per_window: {
      gfc: {
        total_return: "0.10",
        benchmark_return: "-0.5623",
        excess: "0.6623",
        adjusted_excess: "0.60",
        capital_exposure: 0.43,
        capital_exposure_reconstructed: false,
        max_drawdown: "-0.12",
        trades: 12,
        sessions: 252,
      },
    },
    ...overrides,
  };
}

function leaderboardResponse(overrides: Partial<LeaderboardResponse> = {}): LeaderboardResponse {
  return {
    round_id: "r2-2026-08",
    rank_by: "median",
    purpose: "trading",
    scoring_basis: "adjusted_excess",
    unscored_reason: null,
    windows: [windowBenchmark()],
    rows: [leaderboardRow()],
    ...overrides,
  };
}

function cardSummary(overrides: Partial<CardSummary> = {}): CardSummary {
  return {
    agent_id: "c07-chop",
    display_name: "Chop Specialist",
    discipline: "mean-reversion",
    universe: ["SPY", "GLD"],
    entry: "rsi_below(30)",
    exit: "rsi_above(60)",
    stop_loss_pct: "0.05",
    take_profit_pct: "0.10",
    max_hold_days: 20,
    max_positions: 5,
    position_pct: "0.10",
    designed_through: "2026-06-30",
    thesis: "Mean reversion in choppy, range-bound markets.",
    ...overrides,
  };
}

function libraryResponse(overrides: Partial<LibraryResponse> = {}): LibraryResponse {
  return {
    tiers: [
      { tier: "base", label: "Base", cards: [cardSummary()] },
      { tier: "variants", label: "Variants", cards: [] },
      { tier: "candidates", label: "Candidates", cards: [] },
      { tier: "retired", label: "Retired", cards: [] },
    ],
    ...overrides,
  };
}

function tradeDetail(overrides: Partial<TradeDetail> = {}): TradeDetail {
  return {
    symbol: "GLD",
    entry_date: "2008-03-04",
    exit_date: "2008-09-11",
    entry_price: "90.00",
    exit_price: "110.00",
    quantity: "100",
    bars_held: 130,
    exit_reason: "rule",
    return_pct: "0.22",
    pnl: "2000.00",
    contribution: "0.05",
    unrealised: false,
    ...overrides,
  };
}

function agentWindowDetail(overrides: Partial<AgentWindowDetail> = {}): AgentWindowDetail {
  return {
    window: "gfc",
    sessions: 252,
    starting_equity: "100000.00",
    ending_equity: "110000.00",
    total_return: "0.10",
    benchmark_return: "-0.5623",
    excess: "0.6623",
    adjusted_excess: "0.60",
    capital_exposure: 0.43,
    max_drawdown: "-0.12",
    win_rate: 0.5,
    profit_factor: "1.8",
    unrealised_share: "0.0123",
    top3_share_of_gross_wins: 0.71,
    return_without_top3_winners: "0.02",
    rejections: [],
    trades: [tradeDetail()],
    ...overrides,
  };
}

function agentDetailResponse(overrides: Partial<AgentDetailResponse> = {}): AgentDetailResponse {
  return {
    round_id: "r2-2026-08",
    agent_id: "c07-chop",
    display_name: "Chop Specialist",
    card: cardSummary(),
    windows: [agentWindowDetail()],
    ...overrides,
  };
}

function jobCreated(overrides: Partial<JobCreated> = {}): JobCreated {
  return {
    job_id: "job-1",
    status: "queued",
    round_id: "r3-2026-08",
    total_runs: 2,
    created_at: "2026-08-21T00:00:00Z",
    ...overrides,
  };
}

function jobStatus(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    job_id: "job-1",
    status: "running",
    round_id: "r3-2026-08",
    cards: ["c07-chop"],
    windows: ["gfc"],
    total_runs: 2,
    completed_runs: 1,
    failed_runs: 0,
    current: { window: "gfc", agent_id: "c07-chop" },
    created_at: "2026-08-21T00:00:00Z",
    started_at: "2026-08-21T00:00:01Z",
    finished_at: null,
    elapsed_seconds: 12.3,
    log: ["starting c07-chop on gfc"],
    results: [],
    error: null,
    ...overrides,
  };
}

function gateOutcome(overrides: Partial<GateOutcome> = {}): GateOutcome {
  return {
    agent_id: "c07-chop",
    passed: true,
    reason: "cleared the minimum window count",
    detail: { windows_run: "6/6" },
    ...overrides,
  };
}

function selectionSeat(overrides: Partial<SelectionSeat> = {}): SelectionSeat {
  return {
    agent_id: "c07-chop",
    rank: 1,
    live_median: "+7.41%",
    live_hits: "4/6",
    novel_names: "1.32",
    seated: true,
    seated_by: "rule",
    note: "Top of the ranking on median excess.",
    ...overrides,
  };
}

function selectionResponse(overrides: Partial<SelectionResponse> = {}): SelectionResponse {
  return {
    round_id: "r2-2026-08",
    rule_version: "2026.08",
    gates: {
      A: [gateOutcome()],
      L: [gateOutcome({ reason: "sufficient liquidity" })],
      C: [gateOutcome({ reason: "consistent across windows" })],
    },
    ranking: [selectionSeat()],
    seats: [selectionSeat()],
    notes: ["Live medians are drawn from a 6-window sample and may not generalise."],
    ...overrides,
  };
}

function findingsResponse(overrides: Partial<FindingsResponse> = {}): FindingsResponse {
  const carried = {
    id: "r2-defect-1",
    round_id: "r2-2026-08",
    kind: "defect" as const,
    title: "D1 — total_return is rebased to the first session's close",
    body: "Found while reconciling total_return against ending_equity.",
    source: "DEFECTS.md § D1",
    carries_forward: true,
  };
  return {
    round_id: "r2-2026-08",
    findings: [carried],
    // `follow_ups` is a filtered VIEW of `findings`, never a disjoint list -- the same entry, by id.
    follow_ups: [carried],
    sources: ["DEFECTS.md"],
    ...overrides,
  };
}

async function renderCompetition() {
  render(
    <MemoryRouter>
      <Competition />
    </MemoryRouter>,
  );
  // Summary and Leaderboard are now the same default "Rounds" view -- there is no separate
  // Leaderboard tab to switch to any more, so this just waits for the leaderboard table's own
  // heading to confirm the round's data has loaded. Tests that care about Findings/Selection/etc.
  // click their own tab and must not rely on this helper's landing view.
  await screen.findByText(/Leaderboard —/);
}


function roundNarrative(overrides: Partial<RoundNarrative> = {}): RoundNarrative {
  return {
    round_id: "r2-2026-08",
    title: "Round 2 - the promotion rule",
    focus: "Whether a promotion resting on one recompute is evidence.",
    headline: "The promotion rule double-counts a deterministic recompute.",
    outcome: "First paragraph of the outcome.\n\nSecond paragraph of the outcome.",
    seated: [],
    owner_override: null,
    carries_forward: ["Re-run the promotion check against new windows."],
    sources: ["data/rounds/r2-2026-08/REPORT.md"],
    ...overrides,
  };
}

function nextRoundBriefing(overrides: Partial<NextRoundBriefing> = {}): NextRoundBriefing {
  return {
    previous_round_id: "r2-2026-08",
    next_round_id: "r3-2026-08",
    plan_path: null,
    pre_registered: false,
    focus: null,
    authored_carries_forward: ["Re-run the promotion check against new windows."],
    carries_forward: [],
    blockers: ["No plan is committed for r3-2026-08."],
    ...overrides,
  };
}

beforeEach(() => {
  roundsMock.mockReset();
  libraryMock.mockReset();
  windowsMock.mockReset();
  leaderboardMock.mockReset();
  agentDetailMock.mockReset();
  createJobMock.mockReset();
  jobMock.mockReset();
  cancelJobMock.mockReset();
  selectionMock.mockReset();
  findingsMock.mockReset();
  findingsMock.mockResolvedValue(findingsResponse());
  narrativeMock.mockReset();
  narrativeMock.mockResolvedValue(roundNarrative());
  nextRoundMock.mockReset();
  nextRoundMock.mockResolvedValue(nextRoundBriefing());

  roundsMock.mockResolvedValue({ rounds: [roundSummary()] });
  libraryMock.mockResolvedValue(libraryResponse());
  windowsMock.mockResolvedValue({ windows: DEFAULT_WINDOW_CATALOGUE });
  leaderboardMock.mockResolvedValue(leaderboardResponse());
  agentDetailMock.mockResolvedValue(agentDetailResponse());
  // The Selection view fetches eagerly on round change, independent of which tab is active (matching
  // the leaderboard/library/windows effects) -- every test needs a resolved default here, not only
  // the ones that exercise the Selection tab directly, or the effect's own `.then()` throws on mount.
  selectionMock.mockResolvedValue(selectionResponse());
});

describe("leaderboard ordering and the pinned SPY row", () => {
  it("renders rows in rank order with the SPY benchmark row carrying each window's benchmark return", async () => {
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        windows: [
          windowBenchmark({ window: "gfc", benchmark_return: "-0.5623" }),
          windowBenchmark({ window: "covid", benchmark_return: "0.3000" }),
        ],
        rows: [
          leaderboardRow({ rank: 2, agent_id: "b-momentum", display_name: "Momentum B", per_window: {} }),
          leaderboardRow({ rank: 1, agent_id: "c07-chop", display_name: "Chop Specialist", per_window: {} }),
        ],
      }),
    );
    await renderCompetition();

    const table = (await screen.findByText("SPY (benchmark)")).closest("table") as HTMLTableElement;
    const tbody = table.querySelector("tbody") as HTMLTableSectionElement;
    const rows = Array.from(tbody.rows);

    // The SPY row is pinned first, then agents in ascending rank order (1 before 2), regardless of
    // the order the server happened to list them in the fixture above.
    expect(rows[0]?.textContent).toContain("SPY (benchmark)");
    expect(rows[1]?.textContent).toContain("Chop Specialist");
    expect(rows[2]?.textContent).toContain("Momentum B");

    // SPY's own return for each window is visible right there in the table, not only in a drill-down.
    expect(within(rows[0] as HTMLElement).getByText("-56.23%")).toBeTruthy();
    expect(within(rows[0] as HTMLElement).getByText("+30.00%")).toBeTruthy();
  });
});

describe("the leaderboard carries the programme's verdict", () => {
  it("renders the 'No durable edge' pill in the leaderboard header, so rank 1 never reads as a winner alone", async () => {
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        rows: [leaderboardRow({ rank: 1, display_name: "Chop Specialist", per_window: {} })],
      }),
    );
    await renderCompetition();

    // The heading and the pill are on the same line: the verdict travels with the table it
    // qualifies rather than living only on `/strategy`, a page this reader may never open.
    const pill = await screen.findByTestId("comp-leaderboard-verdict");
    expect(pill.textContent).toBe("No durable edge");
    expect(pill.className).toContain("status-pill-warn");

    const head = pill.closest(".comp-leaderboard-head") as HTMLElement;
    expect(within(head).getByText(/Leaderboard —/)).toBeTruthy();

    // And the Rank column is still there -- the fix is to qualify the ranking, not remove it.
    expect(screen.getByText("Rank")).toBeTruthy();
  });
});

describe("null metrics never render as zero", () => {
  it("renders a null median/worst excess as an em dash, never 0 or 0.00%", async () => {
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        rows: [
          leaderboardRow({
            agent_id: "c07-chop",
            display_name: "Chop Specialist",
            median_excess: null,
            worst_excess: null,
            per_window: {},
          }),
        ],
      }),
    );
    await renderCompetition();

    const row = (await screen.findByText("Chop Specialist")).closest("tr") as HTMLElement;
    expect(within(row).getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(within(row).queryByText("0.00%")).toBeNull();
    expect(within(row).queryByText("0%")).toBeNull();
  });
});

describe("provenance-constrained windows and ineligible rows", () => {
  it("marks a provenance_constrained window and an ineligible row with its window count", async () => {
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        windows: [
          windowBenchmark({ window: "gfc", provenance_constrained: false }),
          windowBenchmark({ window: "13f-legal", provenance_constrained: true }),
        ],
        rows: [
          leaderboardRow({
            agent_id: "b-momentum",
            display_name: "Momentum B",
            eligible: false,
            windows_run: 0,
            per_window: {},
          }),
        ],
      }),
    );
    await renderCompetition();

    // "not comparable" now renders twice -- once in Summary's own window-detail strip and once in the
    // Leaderboard table's column header -- since the merge puts both sections in the same view over
    // the same round's windows. `findAllByText` (plural), not `findByText`, for exactly that reason.
    expect((await screen.findAllByText("not comparable")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/13f-legal/).length).toBeGreaterThan(0);

    // Only "gfc" is comparable (the other window is provenance_constrained), so an ineligible row
    // that ran zero windows reads "ran 0 of 1 windows". This is Leaderboard-only text (Summary has no
    // per-row eligibility badge), so it still renders exactly once.
    expect(screen.getByText(/ran 0 of 1 windows/)).toBeTruthy();
  });
});

describe("agent drill-down", () => {
  it("opens inline under the Leaderboard table when a row is clicked -- there is no separate 'Card' tab any more", async () => {
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        rows: [leaderboardRow({ agent_id: "c07-chop", display_name: "Chop Specialist", per_window: {} })],
      }),
    );
    agentDetailMock.mockResolvedValue(
      agentDetailResponse({
        windows: [
          agentWindowDetail({
            trades: [
              tradeDetail({ symbol: "GLD", unrealised: true, pnl: "500.00", contribution: "0.02" }),
              tradeDetail({ symbol: "SPY", unrealised: false, pnl: "-100.00", contribution: "-0.01" }),
            ],
          }),
        ],
      }),
    );
    await renderCompetition();

    // The dead "Card" tab is gone from the rail entirely, and so is the separate "Leaderboard" tab --
    // it is merged into the same "Rounds" tab this table already renders under.
    expect(screen.queryByRole("tab", { name: "Card" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Leaderboard" })).toBeNull();

    fireEvent.click(await screen.findByText("Chop Specialist"));

    // Still on the Rounds tab -- the drill-down renders inline underneath the table, not on a tab of
    // its own.
    const roundsTab = screen.getByRole("tab", { name: "Rounds" });
    expect(roundsTab.getAttribute("aria-selected")).toBe("true");
    expect(agentDetailMock).toHaveBeenCalledWith("r2-2026-08", "c07-chop");

    const goldRow = (await screen.findByText("GLD")).closest("tr") as HTMLElement;
    expect(within(goldRow).getByText(/mark, not realized/i)).toBeTruthy();

    const spyRow = screen.getByText("SPY").closest("tr") as HTMLElement;
    expect(within(spyRow).queryByText(/mark, not realized/i)).toBeNull();

    // The drawer's own close button clears it back to the bare leaderboard.
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("GLD")).toBeNull();
  });

  it("opens the drawer inline when a best-card link is clicked from the Summary window-detail strip", async () => {
    // The default leaderboard fixture's row carries a "gfc" per_window entry with excess "0.6623",
    // which is what Summary's window-detail strip renders its best-card link from.
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    // "Rounds" is the default (and only) view for Summary/Leaderboard now -- no tab click needed.
    const roundsTab = await screen.findByRole("tab", { name: "Rounds" });

    fireEvent.click(await screen.findByRole("button", { name: /Chop Specialist \+66\.23%/ }));

    // `onSelectAgent` from Summary's window-detail strip just selects the agent -- there is no other
    // view to switch to any more, since Leaderboard (where the drawer renders) is the same view.
    expect(roundsTab.getAttribute("aria-selected")).toBe("true");
    expect(agentDetailMock).toHaveBeenCalledWith("r2-2026-08", "c07-chop");
    expect(await screen.findByRole("heading", { name: /Chop Specialist — r2-2026-08/ })).toBeTruthy();
  });
});

describe("the library renders as a compact table, detail behind a per-row expand", () => {
  async function openLibraryTab() {
    fireEvent.click(screen.getByRole("tab", { name: "Next round" }));
    await screen.findByRole("heading", { name: "Base" });
  }

  it("renders the tier's cards as a table with a Card/Universe/Entry/Exit row for each card", async () => {
    await renderCompetition();
    await openLibraryTab();

    const baseHeading = await screen.findByRole("heading", { name: "Base" });
    // The tier panel is the `.panel` wrapping the heading, so scoping to it (rather than the whole
    // document) proves this specific tier's cards render as its own table, not merely that some
    // table exists somewhere on the page.
    const tierPanel = baseHeading.closest(".panel") as HTMLElement;
    const table = within(tierPanel).getByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(
      expect.arrayContaining(["Card", "Universe", "Entry", "Exit"]),
    );

    const row = within(table).getByText("Chop Specialist").closest("tr") as HTMLElement;
    expect(within(row).getByText("c07-chop")).toBeTruthy();
    expect(within(row).getByText("SPY, GLD")).toBeTruthy();
    expect(within(row).getByText("rsi_below(30)")).toBeTruthy();
    expect(within(row).getByText("rsi_above(60)")).toBeTruthy();
  });

  it("keeps a card's thesis behind a collapsed <details>, reachable by opening it", async () => {
    await renderCompetition();
    await openLibraryTab();

    const baseHeading = await screen.findByRole("heading", { name: "Base" });
    const tierPanel = baseHeading.closest(".panel") as HTMLElement;
    const row = within(tierPanel).getByText("Chop Specialist").closest("tr") as HTMLElement;
    const details = within(row).getByText("Mean reversion in choppy, range-bound markets.").closest(
      "details",
    ) as HTMLDetailsElement;
    expect(details).toBeTruthy();
    // Collapsed by default -- the whole point of moving the thesis behind an expand.
    expect(details.open).toBe(false);

    fireEvent.click(within(row).getByText("Detail"));
    expect(details.open).toBe(true);
  });
});

describe("the run form and job creation", () => {
  async function openLibraryTab() {
    fireEvent.click(screen.getByRole("tab", { name: "Next round" }));
    // "Base" also appears as an <option> in the (optional) tier select, so this is scoped to the
    // tier's own section heading rather than matched as plain text.
    await screen.findByRole("heading", { name: "Base" });
  }

  it("calls createJob with the selected cards and windows", async () => {
    await renderCompetition();
    await openLibraryTab();

    // gfc and covid are both "main" windows and start checked by default; unchecking covid isolates
    // gfc as the only selected window without ever clicking an already-checked box off by accident.
    await screen.findByLabelText(/^gfc\b/);
    fireEvent.change(screen.getByLabelText("Round id"), { target: { value: "r3-2026-08" } });
    fireEvent.click(screen.getByLabelText("Chop Specialist"));
    fireEvent.click(screen.getByLabelText(/^covid\b/));

    createJobMock.mockResolvedValue(jobCreated());

    fireEvent.click(screen.getByRole("button", { name: "Run round" }));

    await screen.findByText(/0 \/ 2 runs complete/);
    expect(createJobMock).toHaveBeenCalledWith({
      round_id: "r3-2026-08",
      cards: ["c07-chop"],
      windows: ["gfc"],
    });
  });

  it("renders a 409 as a plain message naming the already-running job, not a stack trace", async () => {
    await renderCompetition();
    await openLibraryTab();

    await screen.findByLabelText(/^gfc\b/);
    fireEvent.change(screen.getByLabelText("Round id"), { target: { value: "r3-2026-08" } });
    fireEvent.click(screen.getByLabelText("Chop Specialist"));
    fireEvent.click(screen.getByLabelText(/^covid\b/));

    createJobMock.mockRejectedValue(
      new ApiRequestError(
        409,
        "A round is already running: job job-old-77. Wait for it to finish or cancel it first.",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Run round" }));

    expect(await screen.findByText(/job-old-77/)).toBeTruthy();
    expect(screen.queryByText(/at Object\.|at async|TypeError|\.tsx:\d+/)).toBeNull();
  });

  it("offers windows even when rounds() returns an empty list -- the case the old rounds-derived list could not serve", async () => {
    roundsMock.mockResolvedValue({ rounds: [] });
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    // With zero rounds the leaderboard never has a round to load, so this page waits on the
    // rounds-empty placeholder instead of `renderCompetition()`'s usual "Leaderboard —" signal. In
    // the merged "Rounds" view `SummarySection` is the one that reports the shared `/rounds` fetch --
    // `LeaderboardSection` is `embedded` and drops its own copy -- so this waits on Summary's line.
    await screen.findByText("No rounds have been run yet.");
    await openLibraryTab();

    const gfcCheckbox = (await screen.findByLabelText(/^gfc\b/)) as HTMLInputElement;
    const covidCheckbox = screen.getByLabelText(/^covid\b/) as HTMLInputElement;
    const legalCheckbox = screen.getByLabelText(/^13f-legal\b/) as HTMLInputElement;

    // Main windows default on, so the common case (run the eight regime windows) is one click.
    expect(gfcCheckbox.checked).toBe(true);
    expect(covidCheckbox.checked).toBe(true);
    // The non-main window is visibly marked and defaults off.
    expect(legalCheckbox.checked).toBe(false);
    expect(screen.getByText("not a regime window")).toBeTruthy();
  });
});

describe("round-5 horizon ladder: windows grouped by horizon in the run form", () => {
  async function openLibraryTab() {
    fireEvent.click(screen.getByRole("tab", { name: "Next round" }));
    await screen.findByRole("heading", { name: "Base" });
  }

  it("renders horizon groups in 6m -> 10y order with a heading naming each group's window count", async () => {
    // Deliberately out of horizon order and interleaved, mirroring how little the backend's own
    // array order can be trusted -- the form must impose 6m -> 10y itself, not reflect the wire order.
    windowsMock.mockResolvedValue({
      windows: [
        windowCatalogueEntry({ window: "h10y-1", start: "2016-01-01", end: "2026-01-01", horizon: "10y", matrix: "r5-ladder" }),
        windowCatalogueEntry({ window: "h1y-1", start: "2025-01-01", end: "2026-01-01", horizon: "1y", matrix: "r5-ladder" }),
        windowCatalogueEntry({ window: "h1y-2", start: "2024-01-01", end: "2025-01-01", horizon: "1y", matrix: "r5-ladder" }),
        windowCatalogueEntry({ window: "h6m-1", start: "2025-07-01", end: "2026-01-01", horizon: "6m", matrix: "r5-ladder" }),
      ],
    });
    await renderCompetition();
    await openLibraryTab();

    const fieldset = (await screen.findByText("Windows")).closest("fieldset") as HTMLElement;
    const headings = within(fieldset).getAllByRole("heading", { level: 4 });
    expect(headings.map((h) => h.textContent)).toEqual([
      "6 months (1 window)",
      "1 year (2 windows)",
      "10 years (1 window)",
    ]);

    // Each heading precedes its own group's checkboxes in document order (6m before h6m-1, etc.) --
    // proven by the group's own count matching, not merely that the label text exists somewhere.
    expect(within(fieldset).getByLabelText(/^h6m-1\b/)).toBeTruthy();
    expect(within(fieldset).getByLabelText(/^h1y-1\b/)).toBeTruthy();
    expect(within(fieldset).getByLabelText(/^h1y-2\b/)).toBeTruthy();
    expect(within(fieldset).getByLabelText(/^h10y-1\b/)).toBeTruthy();
  });

  it("still renders a horizon: null window in the legacy, ungrouped presentation", async () => {
    windowsMock.mockResolvedValue({
      windows: [
        windowCatalogueEntry({ window: "gfc", horizon: null, matrix: "r2" }),
        windowCatalogueEntry({ window: "h6m-1", start: "2025-07-01", end: "2026-01-01", horizon: "6m", matrix: "r5-ladder" }),
      ],
    });
    await renderCompetition();
    await openLibraryTab();

    const fieldset = (await screen.findByText("Windows")).closest("fieldset") as HTMLElement;
    // "gfc" renders exactly as rounds 1-4 always have: selectable, with no horizon heading above it.
    const gfcCheckbox = within(fieldset).getByLabelText(/^gfc\b/) as HTMLInputElement;
    expect(gfcCheckbox).toBeTruthy();
    expect(gfcCheckbox.checked).toBe(true); // `main: true` by the factory default, seeded on.

    // The one horizon-tagged window still gets its own group heading.
    const headings = within(fieldset).getAllByRole("heading", { level: 4 });
    expect(headings.map((h) => h.textContent)).toEqual(["6 months (1 window)"]);
  });

  it("visibly distinguishes a r5-bear window from a r5-ladder window of the same horizon", async () => {
    windowsMock.mockResolvedValue({
      windows: [
        windowCatalogueEntry({
          window: "h6m-1",
          start: "2025-07-01",
          end: "2026-01-01",
          label: "calendar-sampled",
          horizon: "6m",
          matrix: "r5-ladder",
        }),
        windowCatalogueEntry({
          window: "b6m-1",
          start: "2022-01-01",
          end: "2022-07-01",
          label: "falling benchmark",
          horizon: "6m",
          matrix: "r5-bear",
        }),
      ],
    });
    await renderCompetition();
    await openLibraryTab();

    const fieldset = (await screen.findByText("Windows")).closest("fieldset") as HTMLElement;
    // Both windows share the "6 months" group -- exactly the case where mixing them silently would
    // hide the round's own selection effect.
    expect(within(fieldset).getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual([
      "6 months (2 windows)",
    ]);

    const ladderLabel = within(fieldset).getByLabelText(/^h6m-1\b/).closest("label") as HTMLElement;
    const bearLabel = within(fieldset).getByLabelText(/^b6m-1\b/).closest("label") as HTMLElement;

    expect(within(bearLabel).getByText("bear")).toBeTruthy();
    expect(within(ladderLabel).queryByText("bear")).toBeNull();
  });
});

describe("job progress polling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders progress for a running job and stops calling job() once it reports succeeded", async () => {
    await renderCompetition();
    fireEvent.click(screen.getByRole("tab", { name: "Next round" }));
    await screen.findByRole("heading", { name: "Base" });

    await screen.findByLabelText(/^gfc\b/);
    fireEvent.change(screen.getByLabelText("Round id"), { target: { value: "r3-2026-08" } });
    fireEvent.click(screen.getByLabelText("Chop Specialist"));

    createJobMock.mockResolvedValue(jobCreated({ status: "queued", total_runs: 2 }));

    vi.useFakeTimers();

    fireEvent.click(screen.getByRole("button", { name: "Run round" }));

    // Flush the `createJob()` promise and the state update it seeds -- plain microtask ticks, which
    // fake timers do not gate (only setTimeout/setInterval are faked).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/0 \/ 2 runs complete/)).toBeTruthy();
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(jobMock).not.toHaveBeenCalled();

    // First poll tick: ~2000ms later.
    jobMock.mockResolvedValue(jobStatus({ status: "running", completed_runs: 1, total_runs: 2 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(jobMock).toHaveBeenCalledTimes(1);
    expect(jobMock).toHaveBeenCalledWith("job-1");
    expect(screen.getByText(/1 \/ 2 runs complete/)).toBeTruthy();
    expect(screen.getByText("Running")).toBeTruthy();

    // Second poll tick: the job finishes.
    jobMock.mockResolvedValue(
      jobStatus({ status: "succeeded", completed_runs: 2, total_runs: 2, current: null }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(jobMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/2 \/ 2 runs complete/)).toBeTruthy();
    expect(screen.getByText("Succeeded")).toBeTruthy();

    // Further wall-clock time passes, but the interval was cleared on the terminal status -- no more
    // calls to job().
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000 * 5);
    });
    expect(jobMock).toHaveBeenCalledTimes(2);
  });
});

describe("selection view", () => {
  it("switches to the Selection tab and renders the round's roster, gates, and full ranking", async () => {
    await renderCompetition();
    fireEvent.click(screen.getByRole("tab", { name: "Selection" }));

    const selectionTab = screen.getByRole("tab", { name: "Selection" });
    expect(selectionTab.getAttribute("aria-selected")).toBe("true");
    expect(selectionMock).toHaveBeenCalledWith("r2-2026-08");

    expect(await screen.findByText("Desk roster")).toBeTruthy();
    expect(screen.getByText("Gate A")).toBeTruthy();
    expect(screen.getByText("Gate L")).toBeTruthy();
    expect(screen.getByText("Gate C")).toBeTruthy();
    expect(screen.getByText("Full ranking")).toBeTruthy();
  });

  it("distinguishes a seat won on the rule from one seated outside it", async () => {
    selectionMock.mockResolvedValue(
      selectionResponse({
        seats: [
          selectionSeat({ agent_id: "c07-chop", rank: 1, seated_by: "rule" }),
          selectionSeat({
            agent_id: "c09-macro",
            rank: null,
            seated_by: "owner-override",
            note: "Kept on the desk by the owner despite missing the ranking cut.",
          }),
        ],
      }),
    );
    await renderCompetition();
    fireEvent.click(screen.getByRole("tab", { name: "Selection" }));

    const rosterHeading = await screen.findByText("Desk roster");
    const rosterPanel = rosterHeading.closest(".panel") as HTMLElement;

    const ruleRow = within(rosterPanel).getByText("c07-chop").closest("tr") as HTMLElement;
    expect(within(ruleRow).getByText("Seated by rule")).toBeTruthy();

    const overrideRow = within(rosterPanel).getByText("c09-macro").closest("tr") as HTMLElement;
    expect(within(overrideRow).getByText("Owner override")).toBeTruthy();
    // The seat won outside the rule must never carry the same badge text as a rule win.
    expect(within(overrideRow).queryByText("Seated by rule")).toBeNull();
    expect(overrideRow.className).toContain("selection-seat-nonrule-row");
    expect(ruleRow.className).not.toContain("selection-seat-nonrule-row");
  });

  it("marks a failing gate row as failed, visually distinct from a passing row", async () => {
    selectionMock.mockResolvedValue(
      selectionResponse({
        gates: {
          A: [
            gateOutcome({ agent_id: "c07-chop", passed: true, reason: "cleared" }),
            gateOutcome({ agent_id: "c09-macro", passed: false, reason: "ran too few windows" }),
          ],
          L: [],
          C: [],
        },
      }),
    );
    await renderCompetition();
    fireEvent.click(screen.getByRole("tab", { name: "Selection" }));

    // Scoped to Gate A's own panel -- "c07-chop" is also the default roster/ranking fixture's agent
    // id, so an unscoped query would match more than one element.
    const gateAHeading = await screen.findByText("Gate A");
    const gateAPanel = gateAHeading.closest(".panel") as HTMLElement;

    const failRow = within(gateAPanel).getByText("c09-macro").closest("tr") as HTMLElement;
    expect(within(failRow).getByText("Fail")).toBeTruthy();
    expect(failRow.className).toContain("selection-gate-fail-row");

    const passRow = within(gateAPanel).getByText("c07-chop").closest("tr") as HTMLElement;
    expect(within(passRow).getByText("Pass")).toBeTruthy();
    expect(passRow.className).not.toContain("selection-gate-fail-row");
  });

  it("renders every string in notes verbatim and prominently, not tucked away", async () => {
    const notes = [
      "Live medians are drawn from a 6-window sample and may not generalise.",
      "Gate C thresholds were revised mid-round; earlier evaluations used the prior cut.",
    ];
    selectionMock.mockResolvedValue(selectionResponse({ notes }));
    await renderCompetition();
    fireEvent.click(screen.getByRole("tab", { name: "Selection" }));

    for (const note of notes) {
      expect(await screen.findByText(note)).toBeTruthy();
    }
  });

  it("shows a designed empty state, not a blank area, for a round with no selection recorded", async () => {
    selectionMock.mockRejectedValue(new ApiRequestError(404, "no selection recorded for this round"));
    await renderCompetition();
    fireEvent.click(screen.getByRole("tab", { name: "Selection" }));

    // Wording carries the *reason*, not just the absence: a round only lacks a selection because
    // the rule ranks on its own live out-of-sample matrix and this one has none. The picker stays
    // on screen in this state -- it is reached by default on the newest round.
    expect(await screen.findByText(/out-of-sample matrix, which this round lacks/i)).toBeTruthy();
    expect(document.querySelector("#selection-round-select")).not.toBeNull();
  });
});

describe("the round narrative and the next-round briefing", () => {
  it("renders the selected round's narrative on the Rounds tab, one paragraph per blank line", async () => {
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    await screen.findByRole("tab", { name: "Rounds" });

    // `outcome` is plain text by contract, never markdown and never injected as HTML. Asserting on
    // the paragraph count rather than on a substring is what distinguishes a component that split
    // the text from one that dumped the whole string into a single node.
    const outcome = await screen.findByTestId("comp-narrative-outcome");
    expect(outcome.querySelectorAll("p")).toHaveLength(2);
    expect(screen.getByText("The promotion rule double-counts a deterministic recompute.")).toBeTruthy();
  });

  it("renders an owner override when there is one, and no override callout when there is not", async () => {
    narrativeMock.mockResolvedValue(
      roundNarrative({ owner_override: "The owner seated B-momentum over the rule's pick." }),
    );
    const { unmount } = render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    await screen.findByText("The owner seated B-momentum over the rule's pick.");
    unmount();

    // The other direction matters as much: a component that always renders the callout would pass
    // the assertion above and still misreport every round that had no override.
    narrativeMock.mockResolvedValue(roundNarrative({ owner_override: null }));
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    // Wait on the narrative itself, not merely on the page mounting: a narrative that failed to load
    // renders no override callout either, so keying the absence check on the tab alone would pass
    // just as happily on a broken fetch as on a correctly-omitted callout.
    await screen.findByTestId("comp-narrative-outcome");
    expect(screen.queryByTestId("comp-narrative-override")).toBeNull();
  });

  it("warns on the Next round tab when no plan is committed for the next round", async () => {
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Next round" }));

    // `pre_registered: false` is a real blocker, not a cosmetic state: this programme requires a
    // round's plan to be committed before any result for it exists.
    expect(await screen.findByText(/No plan is committed for r3-2026-08\./)).toBeTruthy();
  });

  it("keeps the authored carries-forward list separate from the findings parser's guess", async () => {
    nextRoundMock.mockResolvedValue(
      nextRoundBriefing({
        authored_carries_forward: ["Authored item the round itself recorded."],
        carries_forward: [
          {
            id: "f1",
            round_id: "r2-2026-08",
            kind: "follow-up",
            title: "Parsed item",
            body: "Only the keyword parser thinks this carries forward.",
            source: "REPORT.md",
            carries_forward: true,
          },
        ],
      }),
    );
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Next round" }));

    const authored = await screen.findByTestId("comp-next-authored");
    expect(authored.textContent).toContain("Authored item the round itself recorded.");
    // The parser's read is a heuristic keyword match over prose and is wrong in both directions;
    // merging it into the authored list would present a guess as the round's own word.
    expect(authored.textContent).not.toContain("Parsed item");
  });
});


describe("the Review tab", () => {
  // `PendingSeatsPanel` used to be mounted at the bottom of the Loop tab, under the loop form and
  // `GenerationsPanel`. It now has its own top-level tab so the one human decision on this page (seat,
  // shelve, reject, retire a promoted card) does not require scrolling past loop machinery to reach --
  // see the `View` docstring in `Competition.tsx`. `PendingSeatsPanel` fetches its own data
  // (`evolutionApi.pendingSeats`) and is not mocked here -- this suite only mocks `@/api/competition` --
  // so the unstubbed-fetch guard in `src/test/setup.ts` makes that call reject and the panel render its
  // own error state, exactly as it does when embedded anywhere else without a mock. What this test pins
  // is only that the queue's own heading renders under the Review tab, and that switching to the Loop
  // tab does not also render it -- i.e. the mount moved rather than being duplicated.
  it("renders the review queue's heading when the Review tab is selected", async () => {
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Review" }));

    const reviewTab = screen.getByRole("tab", { name: "Review" });
    expect(reviewTab.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("Paper desk review queue")).toBeTruthy();
  });

  it("does not render the review queue's heading under the Loop tab", async () => {
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Loop" }));

    expect(screen.getByRole("tab", { name: "Loop" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByText("Paper desk review queue")).toBeNull();
  });
});

describe("per-purpose leaderboards", () => {
  it("asks for the trading board by default and names the basis it is ranked on", async () => {
    await renderCompetition();

    expect(leaderboardMock).toHaveBeenCalledWith("r2-2026-08", "median", "trading");
    // The three purposes are ranked on different quantities, so the basis is stated rather than
    // inferred from column headings that look the same on every board.
    expect(screen.getByText(/ranked on/)).toBeTruthy();
    expect(screen.getByText("adjusted_excess")).toBeTruthy();
  });

  it("refetches for the chosen purpose", async () => {
    await renderCompetition();
    leaderboardMock.mockClear();

    fireEvent.change(screen.getByLabelText("Purpose"), { target: { value: "roth" } });

    await vi.waitFor(() =>
      expect(leaderboardMock).toHaveBeenCalledWith("r2-2026-08", "median", "roth"),
    );
  });

  it("renders why a board is empty rather than an empty table", async () => {
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        purpose: "roth",
        scoring_basis: "irr+cagr",
        rows: [],
        unscored_reason: "No round has run any roth-purpose card yet.",
      }),
    );
    // Not `renderCompetition()`: that helper waits for the leaderboard table's own heading, which is
    // exactly what an unscored board does not render. "Rounds" is the default view -- no tab click
    // needed to reach the (merged) leaderboard section any more.
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );

    // An unmeasured purpose and a measured-but-poor one must not render the same way: a bare empty
    // table says "these strategies have nothing to show for themselves" about strategies nobody has
    // run.
    expect(
      await screen.findByText(/No round has run any roth-purpose card yet\./),
    ).toBeTruthy();
    // Scoped to the leaderboard's own table class, not "any table on the page" -- Summary's own
    // window-detail strip (above this section in the merged view) renders its own table for the
    // round's windows regardless of whether the leaderboard itself has any rows.
    expect(document.querySelector(".comp-leaderboard-table")).toBeNull();
  });
});

describe("the leaderboard is a table, not ten buttons", () => {
  it("keeps plain <tr>s and puts a real aria-expanded button in the rank cell", async () => {
    // A11Y-07. `role="button"` on the `<tr>` stripped the row/column semantics a data table exists
    // to express -- ten rows announced as ten buttons, none of them able to say whether the
    // drill-down they open is currently open. The affordance is a real control now.
    leaderboardMock.mockResolvedValue(
      leaderboardResponse({
        rows: [leaderboardRow({ rank: 1, agent_id: "c07-chop", display_name: "Chop Specialist", per_window: {} })],
      }),
    );
    await renderCompetition();

    expect(document.querySelectorAll('tr[role="button"]')).toHaveLength(0);
    expect(document.querySelectorAll("tr[tabindex]")).toHaveLength(0);

    const toggle = screen.getByRole("button", { name: "Rank 1: open Chop Specialist" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // The rank digit is still what a sighted reader sees in the cell.
    expect(toggle.textContent).toBe("1");

    fireEvent.click(toggle);

    expect(agentDetailMock).toHaveBeenCalledWith("r2-2026-08", "c07-chop");
    expect(
      screen.getByRole("button", { name: "Rank 1: open Chop Specialist" }).getAttribute("aria-expanded"),
    ).toBe("true");

    // A control that says it is expanded must be able to collapse what it expanded -- and its own
    // click must not also fire the row's pointer handler and toggle straight back open.
    fireEvent.click(screen.getByRole("button", { name: "Rank 1: open Chop Specialist" }));
    expect(
      screen.getByRole("button", { name: "Rank 1: open Chop Specialist" }).getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("draws a skeleton in the shape of the table while the leaderboard is in flight", async () => {
    // UX-04. A one-line "Loading leaderboard…" collapsed the panel and then snapped it open to a
    // wide table; it also announced nothing. `Skeleton` carries `role="status"`.
    let resolve: ((value: LeaderboardResponse) => void) | undefined;
    leaderboardMock.mockImplementation(
      () =>
        new Promise<LeaderboardResponse>((r) => {
          resolve = r;
        }),
    );
    render(
      <MemoryRouter>
        <Competition />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Loading the leaderboard…")).toBeTruthy();
    expect(document.querySelector(".skeleton-blocks")).toBeTruthy();

    resolve?.(leaderboardResponse());
  });
});

describe("the page header's two actions", () => {
  it("wears the shared quiet button style rather than the accent-filled CTA", async () => {
    // UX-07. Two glowing filled controls above the fold on a page a reader comes to *read* made the
    // side doors look like the page's purpose.
    await renderCompetition();

    const plan = screen.getByRole("button", { name: "Plan the next round" });
    expect(plan.className).toContain("symbol-submit");
    expect(plan.className).not.toContain("comp-run-cta");

    const loop = screen.getByRole("button", { name: "Start the loop" });
    expect(loop.className).toContain("symbol-submit");
    expect(loop.className).not.toContain("comp-run-cta");
  });

  it("reports the loop's state beside the toggle, and says 'Unknown' rather than throwing when /loop cannot be reached", async () => {
    // UX-07's second half. The loop's state used to be readable only on the Overview page's
    // programme strip. `GET /loop` is unreachable in this suite (the setup file's `fetch` throws),
    // which is exactly the failure the guard exists for: an unreachable loop pills as *unknown*,
    // never as a confident "Idle" the page has no evidence for, and never as a thrown render.
    await renderCompetition();

    const toggle = screen.getByRole("button", { name: "Start the loop" });
    const group = toggle.closest(".comp-loop-toggle") as HTMLElement;
    expect(within(group).getByText("Unknown")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// The tab in the URL (finding UX-11).
//
// `?tab=` was already read here, but ONLY as a `useState` initialiser -- it seeded the opening view
// and was then ignored. So a deep link worked exactly once: the reader's next tab click left the URL
// still saying `?tab=loop` while they were three tabs away, sharing that link sent someone to the
// wrong section, and Back walked out of the page instead of back through the tabs. `useTabParam`
// makes the URL the state rather than its seed; these tests pin both halves.
// ---------------------------------------------------------------------------

/** Shows the current route's path + query, so a test can assert the tab landed in the URL without
 *  reaching into the router's internals. */
function CompetitionLocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

function renderCompetitionAt(initialEntry: string) {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <CompetitionLocationProbe />
      <Competition />
    </MemoryRouter>,
  );
}

describe("the active section lives in the URL", () => {
  it("opens directly on the Loop view for /competition?tab=loop", async () => {
    // The Paper Desk's "Promoted · gen N" pill links here. This is the case that already worked.
    renderCompetitionAt("/competition?tab=loop");

    const loopTab = await screen.findByRole("tab", { name: "Loop" });
    expect(loopTab.getAttribute("aria-selected")).toBe("true");
  });

  it("opens directly on the Findings view for /competition?tab=findings", async () => {
    renderCompetitionAt("/competition?tab=findings");

    const findingsTab = await screen.findByRole("tab", { name: "Findings" });
    expect(findingsTab.getAttribute("aria-selected")).toBe("true");
  });

  it("keeps the URL in step with the tab the reader clicks", async () => {
    // The regression this closes: the old `useState` seed meant clicking Findings changed the view
    // and left the URL untouched, so the address bar described a section the reader had left.
    renderCompetitionAt("/competition");

    fireEvent.click(await screen.findByRole("tab", { name: "Findings" }));
    expect(screen.getByTestId("location-probe").textContent).toContain("tab=findings");

    fireEvent.click(screen.getByRole("tab", { name: "Selection" }));
    expect(screen.getByTestId("location-probe").textContent).toContain("tab=selection");
    expect(screen.getByTestId("location-probe").textContent).not.toContain("tab=findings");
  });

  it("preserves a round param already on the URL across a tab click", async () => {
    renderCompetitionAt("/competition?round=r2-2026-08");

    fireEvent.click(await screen.findByRole("tab", { name: "Findings" }));

    const url = screen.getByTestId("location-probe").textContent ?? "";
    expect(url).toContain("tab=findings");
    // A `setSearchParams({ tab })` would have dropped this.
    expect(url).toContain("round=r2-2026-08");
  });

  it("falls back to Rounds for a View member that has no tab button, rather than selecting nothing", async () => {
    // `"agent"` and `"leaderboard"` are still members of the `View` union but have no entry in
    // `VIEW_TABS` -- see that constant's docstring. A link naming one must land on the default,
    // not on a view the rail cannot show as active.
    renderCompetitionAt("/competition?tab=agent");

    const summaryTab = await screen.findByRole("tab", { name: "Rounds" });
    expect(summaryTab.getAttribute("aria-selected")).toBe("true");
  });

  it("falls back to Rounds for an unrecognised ?tab= value", async () => {
    renderCompetitionAt("/competition?tab=not-a-real-tab");

    const summaryTab = await screen.findByRole("tab", { name: "Rounds" });
    expect(summaryTab.getAttribute("aria-selected")).toBe("true");
  });
});

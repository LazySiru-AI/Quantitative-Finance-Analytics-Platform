/**
 * `SummarySection`'s own honesty rules, at render level -- mirrors `Competition.test.tsx`'s approach
 * (fixture factories that match the wire contract field for field, so a drift shows up as a type
 * error) but does not stub `@/api/competition`'s module boundary at all: this component takes every
 * piece of data as a prop and never calls `competitionApi` itself, so there is nothing to mock and
 * nothing that could reach the `setup.ts` fetch guard.
 *
 * What these tests pin, matching the task's definition of done:
 *  - a `null` `median_excess` never renders as `0`/`0.00%`;
 *  - a round with `has_results: false` renders the "no scored results" state, not a generic error or
 *    a state indistinguishable from still loading;
 *  - rounds sort by `sequence`, not by `round_id` as a string (`r13` above `r9`);
 *  - a window absent from a row's `per_window` does not render a manufactured zero.
 */
import type { ComponentProps } from "react";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  LeaderboardResponse,
  LeaderboardRow,
  PerWindowResult,
  RoundSummary,
  WindowBenchmark,
} from "@/api/competition";

import SummarySection from "./SummarySection";

// --- fixtures --------------------------------------------------------------------------------------

function roundSummary(overrides: Partial<RoundSummary> = {}): RoundSummary {
  return {
    round_id: "r2-2026-08",
    label: "r2 — Aug 2026",
    windows: ["gfc", "covid"],
    agents: 22,
    has_report: true,
    has_brief: true,
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

function perWindowResult(overrides: Partial<PerWindowResult> = {}): PerWindowResult {
  return {
    total_return: "0.10",
    benchmark_return: "-0.5623",
    excess: "0.6623",
    adjusted_excess: "0.60",
    capital_exposure: 0.43,
    capital_exposure_reconstructed: false,
    max_drawdown: "-0.12",
    trades: 12,
    sessions: 252,
    ...overrides,
  };
}

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
    per_window: { gfc: perWindowResult() },
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

function baseProps(overrides: Partial<ComponentProps<typeof SummarySection>> = {}) {
  return {
    rounds: [roundSummary()],
    roundsPhase: "loaded" as const,
    roundsMessage: null,
    selectedRoundId: "r2-2026-08",
    onSelectRound: vi.fn(),
    leaderboard: leaderboardResponse(),
    leaderboardPhase: "loaded" as const,
    leaderboardMessage: null,
    onSelectAgent: vi.fn(),
    ...overrides,
  };
}

// --- tests -----------------------------------------------------------------------------------------

describe("null median_excess never renders as zero", () => {
  it("renders an em dash for best/median performer when every row's median_excess is null, never 0 or 0.00%", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            rows: [
              leaderboardRow({
                agent_id: "c07-chop",
                display_name: "Chop Specialist",
                median_excess: null,
                per_window: {},
              }),
            ],
          }),
        })}
      />,
    );

    const bestTile = screen.getByText("Best performer").closest(".tile") as HTMLElement;
    const medianTile = screen.getByText("Median performer").closest(".tile") as HTMLElement;

    expect(within(bestTile).getByText("—")).toBeTruthy();
    expect(within(medianTile).getByText("—")).toBeTruthy();
    expect(within(bestTile).queryByText("0.00%")).toBeNull();
    expect(within(medianTile).queryByText("0.00%")).toBeNull();
    expect(within(bestTile).queryByText("0")).toBeNull();
    expect(within(bestTile).queryByText("0%")).toBeNull();
  });
});

describe("a round with no scored results", () => {
  it("renders the honest 'no scored results' state, not the generic error placeholder", () => {
    const emptyRound = roundSummary({
      round_id: "r9-2026-08",
      label: "r9 — empty",
      has_results: false,
      sequence: 9,
    });
    render(
      <SummarySection
        {...baseProps({
          rounds: [emptyRound],
          selectedRoundId: "r9-2026-08",
          leaderboard: null,
          // The leaderboard fetch for this round would 404 -- this component must not wait on that
          // to arrive before saying so, so this asserts the honest state renders even mid-"loading".
          leaderboardPhase: "loading",
        })}
      />,
    );

    expect(screen.getByText(/has no scored results/)).toBeTruthy();
    expect(screen.queryByText(/Loading round summary/)).toBeNull();
    expect(screen.queryByText(/Could not load/)).toBeNull();

    // The option itself is now just the round's derived name (`roundOption.ts`) -- the marker moved
    // out of the option text, where it made one entry twice the length of its neighbours, and became
    // a pill beside the select about the round actually selected.
    const option = screen.getByRole("option", { name: "r9 · Aug 2026" }) as HTMLOptionElement;
    expect(option.textContent).not.toMatch(/no scored results/);
    const picker = document.querySelector(".summary-round-picker") as HTMLElement;
    expect(within(picker).getByText("No scored results")).toBeTruthy();
  });

  it("also renders the honest state once the doomed fetch actually reports a 404-shaped error", () => {
    const emptyRound = roundSummary({
      round_id: "r9-2026-08",
      label: "r9 — empty",
      has_results: false,
      sequence: 9,
    });
    render(
      <SummarySection
        {...baseProps({
          rounds: [emptyRound],
          selectedRoundId: "r9-2026-08",
          leaderboard: null,
          leaderboardPhase: "error",
          leaderboardMessage: "round not found",
        })}
      />,
    );

    expect(screen.getByText(/has no scored results/)).toBeTruthy();
    expect(screen.queryByText("round not found")).toBeNull();
  });
});

describe("round ordering", () => {
  it("sorts by sequence, not round_id as a string -- r13 renders above r9", () => {
    render(
      <SummarySection
        {...baseProps({
          rounds: [
            roundSummary({ round_id: "r9-2026-05", label: "r9", sequence: 9 }),
            roundSummary({ round_id: "r13-2026-08", label: "r13", sequence: 13 }),
          ],
          selectedRoundId: "r13-2026-08",
        })}
      />,
    );

    const options = screen.getAllByRole("option");
    const labels = options.map((o) => o.textContent ?? "");
    const r13Index = labels.findIndex((l) => l.includes("r13"));
    const r9Index = labels.findIndex((l) => l.includes("r9"));
    expect(r13Index).toBeGreaterThanOrEqual(0);
    expect(r9Index).toBeGreaterThanOrEqual(0);
    expect(r13Index).toBeLessThan(r9Index);
  });
});

describe("per_window is a partial map", () => {
  it("does not render a zero for a window absent from every row's per_window", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            windows: [
              windowBenchmark({ window: "gfc" }),
              windowBenchmark({ window: "covid", benchmark_return: "0.30" }),
            ],
            rows: [
              // This row only ran "gfc" -- "covid" is simply absent from its per_window map, not a
              // zeroed-out entry.
              leaderboardRow({
                agent_id: "c07-chop",
                display_name: "Chop Specialist",
                per_window: { gfc: perWindowResult({ excess: "0.05" }) },
              }),
            ],
          }),
        })}
      />,
    );

    const heading = screen.getByText(/Window detail/);
    const panel = heading.closest(".panel") as HTMLElement;
    const table = within(panel).getByRole("table");
    const rows = within(table).getAllByRole("row");
    // rows[0] is the header; find the "covid" data row specifically.
    const covidRow = rows.find((r) => within(r).queryByText("covid")) as HTMLElement;
    expect(covidRow).toBeTruthy();

    // Nobody ran "covid" -- the best-card-excess cell is an em dash, and the ran-count cell is a real,
    // measured zero (a count, not a withheld metric) rather than the excess column reading "0.00%".
    expect(within(covidRow).getByText("—")).toBeTruthy();
    expect(within(covidRow).queryByText("0.00%")).toBeNull();
    expect(within(covidRow).getByText("0")).toBeTruthy();
  });

  it("computes the best card's excess in a window only from rows that actually have an entry for it", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            windows: [windowBenchmark({ window: "gfc" })],
            rows: [
              leaderboardRow({
                agent_id: "c07-chop",
                display_name: "Chop Specialist",
                per_window: { gfc: perWindowResult({ excess: "0.05" }) },
              }),
              // Ran nothing in "gfc" -- absent entirely, must not be treated as an excess of 0 and
              // must not out-rank the 0.05 card above by being read as a manufactured zero.
              leaderboardRow({
                agent_id: "b-momentum",
                display_name: "Momentum B",
                per_window: {},
              }),
            ],
          }),
        })}
      />,
    );

    expect(screen.getByRole("button", { name: /Chop Specialist \+5\.00%/ })).toBeTruthy();
  });
});

describe("interactivity", () => {
  it("calls onSelectRound when a different option is chosen from the round select", () => {
    const onSelectRound = vi.fn();
    render(
      <SummarySection
        {...baseProps({
          rounds: [
            roundSummary({ round_id: "r1-2026-01", label: "r1", sequence: 1 }),
            roundSummary({ round_id: "r2-2026-08", label: "r2", sequence: 2 }),
          ],
          selectedRoundId: "r2-2026-08",
          onSelectRound,
        })}
      />,
    );

    fireEvent.change(screen.getByLabelText("Round"), { target: { value: "r1-2026-01" } });
    expect(onSelectRound).toHaveBeenCalledWith("r1-2026-01");
  });

  it("calls onSelectAgent when a best-card link in the detail strip is clicked", () => {
    const onSelectAgent = vi.fn();
    render(<SummarySection {...baseProps({ onSelectAgent })} />);

    fireEvent.click(screen.getByRole("button", { name: /Chop Specialist \+66\.23%/ }));
    expect(onSelectAgent).toHaveBeenCalledWith("c07-chop");
  });
});

describe("provenance-constrained windows", () => {
  it("marks a provenance_constrained window but still renders its own row", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            windows: [
              windowBenchmark({ window: "gfc", provenance_constrained: false }),
              windowBenchmark({ window: "13f-legal", provenance_constrained: true }),
            ],
            rows: [leaderboardRow({ per_window: { gfc: perWindowResult() } })],
          }),
        })}
      />,
    );

    expect(screen.getByText("not comparable")).toBeTruthy();
    expect(screen.getAllByText(/13f-legal/).length).toBeGreaterThan(0);
  });
});

describe("the round picker groups scored rounds apart from record-only ones", () => {
  it("puts a scored round and a record-only round in two separately labelled <optgroup>s, never mixed", () => {
    render(
      <SummarySection
        {...baseProps({
          rounds: [
            roundSummary({ round_id: "r16-2026-08", label: "r16 — scored", has_results: true, sequence: 16 }),
            roundSummary({ round_id: "r15-2026-08", label: "r15 — record only", has_results: false, sequence: 15 }),
          ],
          selectedRoundId: "r16-2026-08",
        })}
      />,
    );

    const select = screen.getByLabelText("Round") as HTMLSelectElement;
    const groups = Array.from(select.querySelectorAll("optgroup"));
    const scoredGroup = groups.find((g) => g.label === "Scored") as HTMLOptGroupElement;
    const recordOnlyGroup = groups.find((g) => g.label === "Record only") as HTMLOptGroupElement;

    // Options are named from `round_id` (see `roundOption.ts`), not from the authored label.
    expect(within(scoredGroup).getByRole("option", { name: "r16 · Aug 2026" })).toBeTruthy();
    expect(within(scoredGroup).queryByRole("option", { name: "r15 · Aug 2026" })).toBeNull();

    expect(within(recordOnlyGroup).getByRole("option", { name: "r15 · Aug 2026" })).toBeTruthy();
    expect(within(recordOnlyGroup).queryByRole("option", { name: "r16 · Aug 2026" })).toBeNull();
  });

  it("omits the record-only optgroup entirely when every round has results", () => {
    render(
      <SummarySection
        {...baseProps({
          rounds: [roundSummary({ has_results: true })],
        })}
      />,
    );

    const select = screen.getByLabelText("Round") as HTMLSelectElement;
    const groups = Array.from(select.querySelectorAll("optgroup"));
    expect(groups.some((g) => g.label === "Scored")).toBe(true);
    expect(groups.some((g) => g.label === "Record only")).toBe(false);
  });
});

describe("a record-only round's designed panel", () => {
  it("says it is a written record with no run files, not a generic empty/error state", () => {
    render(
      <SummarySection
        {...baseProps({
          rounds: [
            roundSummary({
              round_id: "r16-2026-08",
              label: "Round 16 - the cash constraint was worth nothing, and found a defect anyway",
              has_results: false,
              windows: [],
              sequence: 16,
            }),
          ],
          selectedRoundId: "r16-2026-08",
          leaderboard: null,
        })}
      />,
    );

    // The round's own label sentence is quoted, not paraphrased away -- it appears both in the
    // picker's own <option> and in the callout below it, so this asserts presence rather than
    // uniqueness.
    expect(
      screen.getAllByText(/Round 16 - the cash constraint was worth nothing, and found a defect anyway/)
        .length,
    ).toBeGreaterThan(0);
    // Names what it actually is (a written record) and what it lacks (run files), and points at
    // where the record itself lives rather than leaving a reader looking at an empty leaderboard.
    // The sentence is split across inline `<code>` tags for the filenames, so this reads the
    // callout's combined text rather than matching a single fragmented text node.
    const callout = document.querySelector(".summary-empty-round") as HTMLElement;
    expect(callout.textContent).toMatch(/written record/);
    expect(within(callout).getByText("SELECTION.md")).toBeTruthy();
    expect(within(callout).getByText("run.txt")).toBeTruthy();
    expect(callout.textContent).toMatch(/not a scored round/);

    // No numeric panels render for a round that has nothing to measure.
    expect(screen.queryByText("This round's numbers")).toBeNull();
    expect(screen.queryByText(/Window detail/)).toBeNull();
  });
});

describe("the Summary view leads with the round's question, not its statistics", () => {
  it("renders 'This round' (the question + windows) before 'Programme scale' before the numbers", () => {
    render(
      <SummarySection
        {...baseProps({
          rounds: [roundSummary({ label: "the cash constraint was worth nothing", windows: ["gfc", "covid"] })],
        })}
      />,
    );

    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent ?? "");
    const orientationIdx = headings.findIndex((t) => t === "This round");
    const scaleIdx = headings.findIndex((t) => t === "Programme scale");
    const numbersIdx = headings.findIndex((t) => t.includes("numbers"));

    expect(orientationIdx).toBeGreaterThanOrEqual(0);
    expect(scaleIdx).toBeGreaterThan(orientationIdx);
    expect(numbersIdx).toBeGreaterThan(scaleIdx);

    // The round's own label sentence renders as the orientation prose (`.summary-orientation-
    // question`), ahead of any figure -- it also appears in the picker pill and possibly a
    // programme-scale tile, so this is scoped to that specific element rather than a bare text match.
    const question = document.querySelector(".summary-orientation-question");
    expect(question?.textContent).toBe("the cash constraint was worth nothing");
    // "gfc"/"covid" also appear in the Window detail table further down the page -- scope to the
    // orientation panel's own window-chip list.
    const chips = document.querySelector(".summary-orientation-window-chips") as HTMLElement;
    expect(within(chips).getByText("gfc")).toBeTruthy();
    expect(within(chips).getByText("covid")).toBeTruthy();
  });
});

describe("the first visible use of a glossary term is defined inline", () => {
  it("wraps the orientation panel's 'Windows run' label in the Independent-windows Term", () => {
    render(<SummarySection {...baseProps()} />);

    const windowsBlock = document.querySelector(".summary-orientation-windows") as HTMLElement;
    const term = within(windowsBlock).getByText("Windows run");
    expect(term.className).toContain("term-word");
    // The tooltip carries the glossary definition, not just a repeated label -- proves this is the
    // `indep` entry (`glossary.ts`) and not a plain span that happens to share a class name.
    expect(within(windowsBlock).getByRole("tooltip").textContent).toContain("Non-overlapping");
  });
});

describe("every margin against SPY states the noise floor it has to clear", () => {
  it("captions a card's median excess with what it is measured against", () => {
    render(<SummarySection {...baseProps()} />);

    // The default fixture's median_excess is a real, non-null figure -- both performer tiles must
    // say what it is a margin against, not sit as a bare percentage.
    const bestTile = screen.getByText("Best performer").closest(".tile") as HTMLElement;
    expect(within(bestTile).getByText(/vs SPY/)).toBeTruthy();
  });

  it("adds the 21.2pp reordering-noise caution when a card's median excess is inside the floor", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            rows: [leaderboardRow({ median_excess: "0.05" })], // 5.00% -- well inside 21.2pp
          }),
        })}
      />,
    );

    const bestTile = screen.getByText("Best performer").closest(".tile") as HTMLElement;
    expect(within(bestTile).getByText(/21\.2pp reordering-noise floor/)).toBeTruthy();
  });

  it("omits the caution once the margin clears the floor", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            rows: [leaderboardRow({ median_excess: "0.30" })], // 30.00% -- clears 21.2pp
          }),
        })}
      />,
    );

    const bestTile = screen.getByText("Best performer").closest(".tile") as HTMLElement;
    expect(within(bestTile).queryByText(/reordering-noise floor/)).toBeNull();
  });

  it("marks a single window's best-card excess as noise when it is inside the floor, in the detail strip", () => {
    render(
      <SummarySection
        {...baseProps({
          leaderboard: leaderboardResponse({
            windows: [windowBenchmark({ window: "gfc" })],
            rows: [
              leaderboardRow({
                per_window: { gfc: perWindowResult({ excess: "0.05" }) }, // 5.00%, inside the floor
              }),
            ],
          }),
        })}
      />,
    );

    // "noise" also appears in the table's own explanatory note above it, and "gfc" also appears in
    // the orientation panel's window chips -- scope to the data row inside the table specifically.
    const table = screen.getByRole("table");
    const row = within(table).getByText("gfc").closest("tr") as HTMLElement;
    expect(within(row).getByText("noise")).toBeTruthy();
  });
});

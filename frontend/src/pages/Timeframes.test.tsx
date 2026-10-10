/**
 * Timeframes: the rule x interval accuracy matrix, and its drill-down.
 *
 * Pins the honesty rules from `docs/research/timeframes/06-interface-contract.md` §5, which are the
 * whole reason this page exists rather than just being a styling exercise:
 *  1. a cell whose `sufficient` is `false` must never render a number -- not a percentage, not `0%`,
 *     not a blank that reads as zero;
 *  2. `lift` is the headline figure; `hit_rate` may only appear as secondary text beside its
 *     `base_rate`, never alone;
 *  3. cross-interval alignment happens on `horizon_minutes`, never `horizon_bars`;
 *  4. a cell's `warnings` must be reachable from the UI;
 *  5. the `4h` column carries a persistent low-confidence marker, independent of any one cell.
 *
 * `@/api/timeframes` is stubbed at the module boundary, the same seam `Overview.test.tsx` and
 * `Ticker.test.tsx` use for their own API clients, so these tests are about rendering the contract's
 * rules correctly, not about JSON parsing. `Chart` is stubbed to a placeholder -- it wraps
 * lightweight-charts, which does not run against jsdom's canvas -- so the drill-down tests below
 * assert the chart *slot* renders once the trace loads, not anything about the candles themselves.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type {
  MatrixQuery,
  MatrixResponse,
  RuleAccuracyCell,
  SignalQuery,
  SignalTrace,
  UniverseEntry,
} from "@/api/timeframes";

const matrixMock = vi.fn<(params: MatrixQuery) => Promise<MatrixResponse>>();
const universeMock = vi.fn<() => Promise<UniverseEntry[]>>();
const signalMock = vi.fn<(params: SignalQuery) => Promise<SignalTrace>>();

vi.mock("@/api/timeframes", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/timeframes")>();
  return {
    ...actual,
    timeframesApi: {
      ...actual.timeframesApi,
      matrix: (params: MatrixQuery) => matrixMock(params),
      universe: () => universeMock(),
      signal: (params: SignalQuery) => signalMock(params),
    },
  };
});

// Heavy (lightweight-charts does not run against jsdom's canvas) and irrelevant to what this page's
// own tests need to pin -- swapped for a marker div, same idiom `Ticker.test.tsx` uses.
vi.mock("@/components/Chart", () => ({ default: () => <div>chart-stub</div> }));

const { default: Timeframes } = await import("@/pages/Timeframes");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function cell(overrides: Partial<RuleAccuracyCell> = {}): RuleAccuracyCell {
  return {
    rule_id: "rsi-oversold",
    interval: "1h",
    scope: "symbol",
    scope_key: "SPY",
    horizon_bars: 20,
    horizon_minutes: 1200,
    horizon_label: "20 bars (~20h)",
    n_raw: 500,
    n_episodes: 40,
    n_independent: 32,
    sufficient: true,
    hit_rate: 0.66,
    base_rate: 0.53,
    lift: 0.13,
    lift_ci_low: 0.05,
    lift_ci_high: 0.21,
    median_return: 0.008,
    baseline_median_return: 0.002,
    p_value: 0.01,
    q_value: 0.02,
    cost_bps_assumed: 5,
    cost_adjusted_edge: 0.11,
    regime: "all",
    first_bar: "2024-01-01",
    last_bar: "2026-08-01",
    warnings: [],
    ...overrides,
  };
}

/** A cell the sample gate rejected -- every measurement field `null`, per contract §2 invariant 1. */
function insufficientCell(overrides: Partial<RuleAccuracyCell> = {}): RuleAccuracyCell {
  return cell({
    sufficient: false,
    hit_rate: null,
    base_rate: null,
    lift: null,
    lift_ci_low: null,
    lift_ci_high: null,
    median_return: null,
    baseline_median_return: null,
    p_value: null,
    q_value: null,
    cost_adjusted_edge: null,
    n_independent: 5,
    n_raw: 40,
    n_episodes: 6,
    ...overrides,
  });
}

function matrixResponse(overrides: Partial<MatrixResponse> = {}): MatrixResponse {
  return {
    cells: [cell()],
    generated_at: "2026-08-26T12:00:00Z",
    coverage: { symbols: 1, intervals: 7, rules: 1, cells_total: 7, cells_sufficient: 1 },
    warnings: [],
    ...overrides,
  };
}

function universe(): UniverseEntry[] {
  return [
    { symbol: "SPY", sector: "Index" },
    { symbol: "AAPL", sector: "Technology" },
  ];
}

function signalTrace(overrides: Partial<SignalTrace> = {}): SignalTrace {
  return {
    symbol: "SPY",
    interval: "1h",
    rule_id: "rsi-oversold",
    expression: "rsi(14) < 30",
    bars: [
      {
        ts: "2026-08-01T00:00:00Z",
        open: 100,
        high: 102,
        low: 99,
        close: 101,
        adj_close: null,
        volume: 10000,
        partial: false,
      },
    ],
    indicators: [],
    fired_at: ["2026-08-01T00:00:00Z"],
    warmup_until: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Timeframes />
    </MemoryRouter>,
  );
}

async function findMatrixTable() {
  const table = await screen.findByRole("table", { name: "Rule by interval accuracy matrix" });
  // `selectedHorizon` starts `null` and only settles to the real bucket in a follow-up effect (see
  // Timeframes.tsx's horizon-tracking `useEffect`) -- every `cellFor` lookup misses on the transient
  // render where it's still `null`, rendering every cell as "n/a" instead of its real data. Waiting
  // for the horizon tab to actually reflect a selection avoids asserting against that transient frame.
  const horizonTablist = screen.queryByRole("tablist", { name: "Horizon" });
  if (horizonTablist) {
    await within(horizonTablist).findByRole("tab", { selected: true });
  }
  return table;
}

beforeEach(() => {
  matrixMock.mockReset();
  universeMock.mockReset();
  signalMock.mockReset();
  universeMock.mockResolvedValue(universe());
  signalMock.mockResolvedValue(signalTrace());
});

// ---------------------------------------------------------------------------

describe("phases", () => {
  it("shows a shaped skeleton, announced politely, while the matrix fetch is in flight", async () => {
    matrixMock.mockReturnValue(new Promise(() => {}));

    const { container } = renderPage();

    // The silhouette: placeholder blocks roughly the height of the grid that is coming, so the
    // panel does not collapse to one line for the length of the fetch and then snap open.
    expect(container.querySelector(".skeleton-rows")).toBeTruthy();
    // And the announcement, which is the half a bare spinner would have dropped.
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("Timeframes");
    expect(status.getAttribute("aria-live")).toBe("polite");
  });

  it("surfaces an ApiRequestError's status and message rather than crashing", async () => {
    matrixMock.mockRejectedValue(new ApiRequestError(500, "boom"));

    renderPage();

    expect(await screen.findByText(/API returned 500: boom/)).toBeTruthy();
    // The page itself is still standing -- controls above the error panel still render.
    expect(screen.getByRole("tablist", { name: "Scope" })).toBeTruthy();
  });

  it("falls back to a generic message for a non-API error, without crashing the page", async () => {
    matrixMock.mockRejectedValue(new TypeError("network down"));

    renderPage();

    expect(await screen.findByText(/Could not load the accuracy matrix/)).toBeTruthy();
  });

  it("shows an explicit empty message when the scope has no computed cells", async () => {
    matrixMock.mockResolvedValue(matrixResponse({ cells: [] }));

    renderPage();

    expect(await screen.findByText(/No cells computed yet for this scope/)).toBeTruthy();
    // The empty phase must not also render the coverage headline or table -- there is nothing to
    // show coverage or rows for.
    expect(screen.queryByText(/cells measurable/)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("matrix rendering", () => {
  it("renders rules as rows and INTERVALS as columns from the mocked grid", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [
          cell({ rule_id: "rsi-oversold", interval: "1h" }),
          cell({ rule_id: "macd-cross", interval: "1d", horizon_bars: 20, horizon_minutes: 28800 }),
        ],
        coverage: { symbols: 1, intervals: 7, rules: 2, cells_total: 14, cells_sufficient: 2 },
      }),
    );

    renderPage();
    const table = await findMatrixTable();

    // Both rule rows present.
    expect(within(table).getByRole("rowheader", { name: "rsi-oversold" })).toBeTruthy();
    expect(within(table).getByRole("rowheader", { name: "macd-cross" })).toBeTruthy();

    // All seven canonical intervals present as columns, regardless of which ones have data.
    for (const iv of ["5m", "15m", "30m", "1h", "4h", "1d", "1w"]) {
      expect(within(table).getByRole("columnheader", { name: new RegExp(`^${iv}`) })).toBeTruthy();
    }

    // A rule/interval combination with no cell in this bucket renders "n/a", not a blank td.
    expect(within(table).getAllByText("n/a").length).toBeGreaterThan(0);
  });

  it("carries a persistent low-confidence marker on the 4h column, independent of any cell", async () => {
    // No cell at all touches "4h" in this fixture -- the marker must still appear, because contract
    // §5 rule 5 places it on the column header unconditionally, not derived from a cell's own data.
    matrixMock.mockResolvedValue(matrixResponse({ cells: [cell({ interval: "1h" })] }));

    renderPage();
    await findMatrixTable();

    const marker = screen.getByTitle(/4h bars alternate 4h\/2\.5h/);
    expect(marker).toBeTruthy();
    expect(marker.getAttribute("aria-label")).toBe("low confidence");
  });
});

describe("contract §5 rule 1 -- insufficient cells never render a number", () => {
  it("shows no percentage for a cell the sample gate rejected", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [insufficientCell({ rule_id: "rsi-oversold", interval: "1h", n_independent: 5 })],
        coverage: { symbols: 1, intervals: 7, rules: 1, cells_total: 7, cells_sufficient: 0 },
      }),
    );

    renderPage();
    await findMatrixTable();

    // Located by its tooltip text, which the insufficient branch always sets (contract §5 rule 4:
    // warnings/insufficiency reason must be reachable) -- not by a CSS class.
    const cellButton = screen.getByTitle(/Insufficient independent sample \(5 of the required 20\)/);
    expect(within(cellButton).getByText("insufficient")).toBeTruthy();
    expect(within(cellButton).getByText(/5 indep/)).toBeTruthy();

    // The assertion that actually matters: nowhere inside this cell's button is there anything that
    // looks like a measured percentage. `formatRate`/`formatSignedRate` always append "%", so its
    // total absence here is direct evidence no number leaked out of the `!cell.sufficient` branch.
    expect(cellButton.textContent).not.toMatch(/%/);
    expect(cellButton.textContent).not.toMatch(/0%/);
  });

  it("still lets an insufficient cell be reachable and open its drill-down", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({ cells: [insufficientCell({ rule_id: "rsi-oversold", interval: "1h" })] }),
    );

    renderPage();
    await findMatrixTable();

    fireEvent.click(screen.getByTitle(/Insufficient independent sample/));

    // The drill-down's own stats panel is also honest about it: "Sufficient" reads "no", and the
    // measurement fields render the withheld dash, never a stray number either.
    expect(await screen.findByText("rsi-oversold @ 1h — SPY")).toBeTruthy();
    const stats = screen.getByText("Sufficient").closest("div") as HTMLElement;
    expect(within(stats).getByText("no")).toBeTruthy();
  });
});

describe("contract §5 rule 2 -- lift is the headline, hit_rate only ever secondary", () => {
  it("renders lift prominently and hit_rate/base_rate paired as secondary text", async () => {
    // hit_rate (0.66) and lift (0.13, from hit_rate 0.66 minus base_rate 0.53) are deliberately far
    // apart, so a test that accidentally asserted on hit_rate instead of lift would fail loudly.
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [cell({ rule_id: "rsi-oversold", interval: "1h", hit_rate: 0.66, base_rate: 0.53 })],
      }),
    );

    renderPage();
    const table = await findMatrixTable();

    const cellButton = within(table).getByRole("button");

    // The headline figure is the lift (hit_rate - base_rate = +13.0%), not the raw hit rate.
    expect(within(cellButton).getByText("+13.0%")).toBeTruthy();
    // hit_rate never appears unpaired -- it is only ever shown beside its own base_rate.
    expect(within(cellButton).getByText("66.0% vs 53.0% base")).toBeTruthy();
    // The raw hit-rate figure never appears as its own standalone headline value.
    expect(within(cellButton).queryByText("66.0%")).toBeNull();

    // Structurally, the lift is the first line printed in the cell -- hit_rate/base_rate come after
    // it in reading order, matching "secondary text beside its base_rate".
    const liftIndex = cellButton.textContent?.indexOf("+13.0%") ?? -1;
    const hitRateIndex = cellButton.textContent?.indexOf("66.0% vs 53.0% base") ?? -1;
    expect(liftIndex).toBeGreaterThanOrEqual(0);
    expect(hitRateIndex).toBeGreaterThan(liftIndex);
  });

  it("also shows lift as the headline stat in the drill-down, with hit_rate/base_rate separate", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [cell({ rule_id: "rsi-oversold", interval: "1h", hit_rate: 0.66, base_rate: 0.53 })],
      }),
    );

    renderPage();
    const table = await findMatrixTable();
    fireEvent.click(within(table).getByRole("button"));

    await screen.findByText("rsi-oversold @ 1h — SPY");
    const liftRow = screen.getByText("Lift").closest("div") as HTMLElement;
    const hitRow = screen.getByText("Hit rate").closest("div") as HTMLElement;
    const baseRow = screen.getByText("Base rate").closest("div") as HTMLElement;
    expect(within(liftRow).getByText("+13.0%")).toBeTruthy();
    expect(within(hitRow).getByText("66.0%")).toBeTruthy();
    expect(within(baseRow).getByText("53.0%")).toBeTruthy();
  });
});

describe("contract §5 rule 3 -- alignment on horizon_minutes, never horizon_bars", () => {
  it("groups cells with equal horizon_minutes into one bucket even when horizon_bars differs", async () => {
    // 20 bars at 1h is 1200 minutes; 5 bars at 4h is also 1200 minutes. Same horizon_minutes,
    // deliberately different horizon_bars -- both must land in the same horizon bucket rather than
    // splitting into two, which grouping on horizon_bars would do.
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [
          cell({
            rule_id: "rsi-oversold",
            interval: "1h",
            horizon_bars: 20,
            horizon_minutes: 1200,
            horizon_label: "20h",
          }),
          cell({
            rule_id: "rsi-oversold",
            interval: "4h",
            horizon_bars: 5,
            horizon_minutes: 1200,
            horizon_label: "20h",
            hit_rate: 0.7,
            base_rate: 0.5,
          }),
        ],
        coverage: { symbols: 1, intervals: 7, rules: 1, cells_total: 14, cells_sufficient: 2 },
      }),
    );

    renderPage();
    const table = await findMatrixTable();

    // A single horizon tab ("20h"), not two -- and both cells' figures are visible at once because
    // they share it.
    expect(screen.getAllByRole("tab", { name: "20h" })).toHaveLength(1);
    expect(within(table).getByText("+13.0%")).toBeTruthy(); // 1h cell: 0.66 - 0.53
    expect(within(table).getByText("+20.0%")).toBeTruthy(); // 4h cell: 0.70 - 0.50
  });

  it("switching the horizon tab changes which cell's figures are shown", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [
          cell({
            rule_id: "rsi-oversold",
            interval: "1h",
            horizon_bars: 20,
            horizon_minutes: 60,
            horizon_label: "short",
            hit_rate: 0.6,
            base_rate: 0.5, // lift +10.0%
          }),
          cell({
            rule_id: "rsi-oversold",
            interval: "1h",
            horizon_bars: 80,
            horizon_minutes: 240,
            horizon_label: "long",
            hit_rate: 0.8,
            base_rate: 0.5, // lift +30.0%
          }),
        ],
        coverage: { symbols: 1, intervals: 7, rules: 1, cells_total: 14, cells_sufficient: 2 },
      }),
    );

    renderPage();
    const table = await findMatrixTable();

    // Default selection is the finest (smallest horizon_minutes) bucket.
    expect(within(table).getByText("+10.0%")).toBeTruthy();
    expect(within(table).queryByText("+30.0%")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "long" }));

    expect(within(table).getByText("+30.0%")).toBeTruthy();
    expect(within(table).queryByText("+10.0%")).toBeNull();

    // Switching horizon is a purely client-side re-filter of the already-fetched grid -- it must not
    // re-hit the matrix endpoint (the whole grid, all horizons, came back on the one fetch).
    expect(matrixMock).toHaveBeenCalledTimes(1);
  });
});

describe("contract §5 rule 4 -- a cell's warnings are reachable", () => {
  it("surfaces a sufficient cell's warnings via its tooltip and in the drill-down", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [
          cell({
            rule_id: "rsi-oversold",
            interval: "1h",
            warnings: ["provider fallback used for 8 of 500 bars"],
          }),
        ],
      }),
    );

    renderPage();
    await findMatrixTable();

    const cellButton = screen.getByTitle("provider fallback used for 8 of 500 bars");
    expect(cellButton).toBeTruthy();

    fireEvent.click(cellButton);

    await screen.findByText("rsi-oversold @ 1h — SPY");
    expect(screen.getByText("Warnings")).toBeTruthy();
    expect(screen.getByText("provider fallback used for 8 of 500 bars")).toBeTruthy();
  });
});

describe("coverage headline", () => {
  it("renders cells_sufficient / cells_total as the honest headline of the feature", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        coverage: { symbols: 4, intervals: 7, rules: 5, cells_total: 140, cells_sufficient: 21 },
      }),
    );

    renderPage();
    await findMatrixTable();

    const headline = screen.getByText(/cells measurable/).closest(".tf-coverage-headline") as HTMLElement;
    expect(within(headline).getByText("21")).toBeTruthy();
    expect(headline.textContent).toContain("140");
    // 21 / 140 = 15% of the grid.
    expect(headline.textContent).toContain("15%");
  });
});

describe("drill-down", () => {
  it("clicking a cell fetches the signal trace for the selected scope/interval/rule", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({ cells: [cell({ rule_id: "rsi-oversold", interval: "1h" })] }),
    );

    renderPage();
    const table = await findMatrixTable();
    fireEvent.click(within(table).getByRole("button"));

    await waitFor(() =>
      expect(signalMock).toHaveBeenCalledWith({ symbol: "SPY", interval: "1h", rule_id: "rsi-oversold" }),
    );

    expect(await screen.findByText("chart-stub")).toBeTruthy();
    // The full statistics panel renders alongside the chart.
    expect(screen.getByText("Cost-adjusted edge")).toBeTruthy();
  });

  it("puts the chart and stats cards inside one equal-height CardGrid", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({ cells: [cell({ rule_id: "rsi-oversold", interval: "1h" })] }),
    );

    renderPage();
    const table = await findMatrixTable();
    fireEvent.click(within(table).getByRole("button"));
    await screen.findByText("chart-stub");

    // `getByText("Cost-adjusted edge")` (the stats card) sits inside a `<dt>` -- its enclosing
    // `.card` is what has to be checked against the grid, not the text node itself.
    const statsCard = screen.getByText("Cost-adjusted edge").closest(".card");
    const chartCard = screen.getByText("chart-stub").closest(".card");
    expect(statsCard).not.toBeNull();
    expect(chartCard).not.toBeNull();
    const grid = statsCard?.closest(".card-grid");
    expect(grid).not.toBeNull();
    // Both halves of the drill-down are tracks of the SAME grid -- the thing that actually makes
    // their bottom edges line up (`Card.css`'s `grid-auto-rows` docstring), not two independently
    // sized panels that merely sit side by side.
    expect(grid?.contains(chartCard as Element)).toBe(true);
  });

  it("closes the drill-down on demand", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({ cells: [cell({ rule_id: "rsi-oversold", interval: "1h" })] }),
    );

    renderPage();
    const table = await findMatrixTable();
    fireEvent.click(within(table).getByRole("button"));
    await screen.findByText("rsi-oversold @ 1h — SPY");

    fireEvent.click(screen.getByRole("button", { name: /close/ }));

    expect(screen.queryByText("rsi-oversold @ 1h — SPY")).toBeNull();
  });

  it("links to the ticker page when the drill-down is scoped to a single symbol", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({ cells: [cell({ rule_id: "rsi-oversold", interval: "1h" })] }),
    );

    renderPage();
    const table = await findMatrixTable();
    fireEvent.click(within(table).getByRole("button"));

    await screen.findByText("rsi-oversold @ 1h — SPY");
    const link = screen.getByRole("link", { name: /SPY/ });
    expect(link.getAttribute("href")).toBe("/symbol/SPY");
  });

  it("does not render a ticker link for a sector/universe-scope drill-down", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [cell({ rule_id: "rsi-oversold", interval: "1h", scope: "sector", scope_key: "Technology" })],
      }),
    );

    renderPage();
    await findMatrixTable();
    fireEvent.click(screen.getByRole("tab", { name: "Sector" }));
    await waitFor(() => expect(matrixMock).toHaveBeenCalledTimes(2));

    const sectorTable = await findMatrixTable();
    fireEvent.click(within(sectorTable).getAllByRole("button")[0] as HTMLElement);

    await screen.findByText(/The chart drill-down needs a single symbol/);
    expect(screen.queryByRole("link", { name: /ticker/i })).toBeNull();
  });

  it("does not fetch a signal trace for a sector/universe scope -- one symbol's trace is undefined there", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({
        cells: [cell({ rule_id: "rsi-oversold", interval: "1h", scope: "sector", scope_key: "Technology" })],
      }),
    );

    renderPage();
    await findMatrixTable();
    fireEvent.click(screen.getByRole("tab", { name: "Sector" }));
    await waitFor(() => expect(matrixMock).toHaveBeenCalledTimes(2));

    const table = await findMatrixTable();
    fireEvent.click(within(table).getAllByRole("button")[0] as HTMLElement);

    expect(
      await screen.findByText(/The chart drill-down needs a single symbol/),
    ).toBeTruthy();
    expect(signalMock).not.toHaveBeenCalled();
  });

  it("surfaces a signal-fetch error rather than crashing the drill-down", async () => {
    matrixMock.mockResolvedValue(
      matrixResponse({ cells: [cell({ rule_id: "rsi-oversold", interval: "1h" })] }),
    );
    signalMock.mockRejectedValue(new ApiRequestError(503, "signal service down"));

    renderPage();
    const table = await findMatrixTable();
    fireEvent.click(within(table).getByRole("button"));

    expect(await screen.findByText(/API returned 503: signal service down/)).toBeTruthy();
  });
});

describe("scope switching re-queries the matrix", () => {
  it("re-fetches with the right params when switching symbol -> sector -> universe", async () => {
    matrixMock.mockResolvedValue(matrixResponse());

    renderPage();
    await findMatrixTable();

    // Universe fetch has resolved and repopulated the symbol picker with real options.
    await screen.findByRole("option", { name: "AAPL" });

    expect(matrixMock).toHaveBeenNthCalledWith(1, { scope: "symbol", symbols: ["SPY"] });

    fireEvent.click(screen.getByRole("tab", { name: "Sector" }));
    await waitFor(() => expect(matrixMock).toHaveBeenCalledTimes(2));
    expect(matrixMock).toHaveBeenNthCalledWith(2, { scope: "sector", sectors: ["Index"] });

    fireEvent.click(screen.getByRole("tab", { name: "Universe" }));
    await waitFor(() => expect(matrixMock).toHaveBeenCalledTimes(3));
    expect(matrixMock).toHaveBeenNthCalledWith(3, { scope: "universe" });

    fireEvent.click(screen.getByRole("tab", { name: "Symbol" }));
    await waitFor(() => expect(matrixMock).toHaveBeenCalledTimes(4));
    expect(matrixMock).toHaveBeenNthCalledWith(4, { scope: "symbol", symbols: ["SPY"] });
  });

  it("re-fetches when the symbol picker itself changes within symbol scope", async () => {
    matrixMock.mockResolvedValue(matrixResponse());

    renderPage();
    await findMatrixTable();
    await screen.findByRole("option", { name: "AAPL" });
    expect(matrixMock).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "AAPL" } });

    await waitFor(() => expect(matrixMock).toHaveBeenCalledTimes(2));
    expect(matrixMock).toHaveBeenNthCalledWith(2, { scope: "symbol", symbols: ["AAPL"] });
  });
});

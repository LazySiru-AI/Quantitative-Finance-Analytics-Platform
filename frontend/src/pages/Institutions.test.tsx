/**
 * The Institutions page's honesty rules, at render level.
 *
 * Mirrors `WashSales.test.tsx`'s approach: the API module is stubbed at the module boundary rather
 * than `fetch` itself. Factory functions mirror the ones in `@/api/institutions.test.ts` so the
 * shapes stay in sync with that file's contract.
 *
 * What these tests pin, matching the task's definition of done:
 *  - a value change never gets mistaken for a share-count change (the Chevron case)
 *  - a null ticker renders the issuer name, not a blank column, and is never fabricated
 *  - a non-null ticker (an owned position) is marked distinctly and is filterable
 *  - shares_pct_change: null renders as "new", never 0% or Infinity
 *  - the counts strip renders the server's own tally, not a client-side recount
 *  - the 13F/NPORT source note and filing provenance (period/filed/accession) are on screen
 *  - the fund selector switches funds and re-fetches
 *  - 404/empty/502/503 states render the right copy without collapsing "unmeasured" into "zero"
 *  - a ticker badge is a real `<a>` (via `Link`) pointed at `/symbol/:symbol`, not an inert span
 *  - the portfolio-shape row (pie + recent moves) sits ahead of "Changes since last filing" and
 *    "Full holdings", fed from the same `snapshot`/`delta` state rather than a third fetch, and
 *    honestly reports a failed snapshot fetch rather than rendering a pie that reads as "holds
 *    nothing"
 *
 *  `HoldingsPieChart` and `RecentMoves` are mocked at the module boundary here, the same way
 *  `institutionsApi` is above: this file's job is to prove `Institutions.tsx` wires the right data
 *  and the right `onSelectTicker` callback into each slot, not to re-test either component's own
 *  rendering -- that belongs in their own test files.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import {
  type FundRef,
  type Holding,
  type HoldingChange,
  type PortfolioDelta,
  type Snapshot,
} from "@/api/institutions";

const fundsMock = vi.fn<() => Promise<{ funds: FundRef[] }>>();
const holdingsMock = vi.fn<(key: string, period?: string) => Promise<Snapshot>>();
const changesMock = vi.fn<(key: string) => Promise<PortfolioDelta>>();

vi.mock("@/api/institutions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/institutions")>();
  return {
    ...actual,
    institutionsApi: {
      ...actual.institutionsApi,
      funds: () => fundsMock(),
      holdings: (key: string, period?: string) => holdingsMock(key, period),
      changes: (key: string) => changesMock(key),
    },
  };
});

/** `useNavigate` is called from `react-router-dom`, which this file also statically imports
 *  (`MemoryRouter`, below) -- unlike `institutionsApi` above, that static import means the
 *  `vi.mock` factory for it runs before ordinary top-level `const` statements, so the fn it
 *  captures has to be defined via `vi.hoisted` rather than a plain `const` declared after this
 *  point, or the factory would read it before initialisation. */
const mockNavigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

/** Stand-ins for the two components another worker builds to the fixed contract this page codes
 *  against (see the task's shared-component contract). Each renders one clickable element per row
 *  it was handed, so a test can assert both *what* data reached the component and that clicking
 *  through calls the `onSelectTicker` this page wired in -- without depending on either component's
 *  real internals, which are out of scope here and may not even exist yet while this page is built. */
vi.mock("@/components/HoldingsPieChart", () => ({
  default: ({
    holdings,
    fundName,
    onSelectTicker,
  }: {
    holdings: Holding[];
    fundName: string;
    topN?: number;
    onSelectTicker?: (ticker: string) => void;
  }) => (
    <div data-testid="holdings-pie-chart" aria-label={`Portfolio shape for ${fundName}`}>
      {holdings.map((h) => (
        <button key={h.cusip} type="button" onClick={() => h.ticker && onSelectTicker?.(h.ticker)}>
          {h.issuer}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/components/RecentMoves", () => ({
  default: ({
    delta,
    phase,
    onSelectTicker,
  }: {
    delta: PortfolioDelta | null;
    phase: string;
    error?: string | null;
    limit?: number;
    onSelectTicker?: (ticker: string) => void;
  }) => (
    <div data-testid="recent-moves">
      {phase === "loaded" &&
        delta?.changes.map((c) => (
          <button key={c.cusip} type="button" onClick={() => c.ticker && onSelectTicker?.(c.ticker)}>
            {c.issuer}
          </button>
        ))}
    </div>
  ),
}));

const { default: Institutions, InstitutionsView } = await import("@/pages/Institutions");

function fund(overrides: Partial<FundRef> = {}): FundRef {
  return {
    key: "BRK",
    name: "Berkshire Hathaway Inc",
    source: "13F",
    cik: "0001067983",
    series_id: null,
    ticker: null,
    principal: null,
    ...overrides,
  };
}

function holding(overrides: Partial<Holding> = {}): Holding {
  return {
    cusip: "166764100",
    issuer: "CHEVRON CORP NEW",
    value: "13990000000",
    shares: "118610534",
    weight: "0.0491",
    ticker: null,
    ...overrides,
  };
}

function snapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    fund: fund(),
    period: "2026-06-30",
    filed: "2026-08-14",
    accession: "0000950123-26-007654",
    total_value: "285000000000",
    holdings: [holding()],
    value_units_rescaled: false,
    ...overrides,
  };
}

function change(overrides: Partial<HoldingChange> = {}): HoldingChange {
  return {
    cusip: "166764100",
    issuer: "CHEVRON CORP NEW",
    ticker: null,
    action: "hold",
    shares_before: "118610534",
    shares_after: "118610534",
    shares_delta: "0",
    shares_pct_change: "0.00",
    value_before: "17460000000",
    value_after: "13990000000",
    value_delta: "-3470000000",
    weight_before: "0.0523",
    weight_after: "0.0491",
    weight_delta: "-0.0032",
    ...overrides,
  };
}

function delta(overrides: Partial<PortfolioDelta> = {}): PortfolioDelta {
  return {
    fund: fund(),
    from_period: "2026-03-31",
    to_period: "2026-06-30",
    from_accession: "0000950123-26-004321",
    to_accession: "0000950123-26-007654",
    total_value_before: "290000000000",
    total_value_after: "285000000000",
    changes: [change()],
    counts: { new: 0, exit: 0, add: 0, trim: 0, hold: 1 },
    median_shares_pct_change: null,
    ...overrides,
  };
}

async function renderInstitutions() {
  render(
    <MemoryRouter>
      <Institutions />
    </MemoryRouter>,
  );
  await screen.findByText(/Changes since last filing/);
}

beforeEach(() => {
  fundsMock.mockReset();
  holdingsMock.mockReset();
  changesMock.mockReset();
  mockNavigate.mockReset();
});

describe("share change and value change are never blurred together", () => {
  it("shows the Chevron case: a hold badge (from shares) beside a large value change labelled as including price movement", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      delta({
        changes: [
          change({
            action: "hold",
            shares_before: "118610534",
            shares_after: "118610534",
            shares_delta: "0",
            value_before: "17460000000",
            value_after: "13990000000",
            value_delta: "-3470000000",
          }),
        ],
        counts: { new: 0, exit: 0, add: 0, trim: 0, hold: 1 },
      }),
    );
    await renderInstitutions();

    // The hide-hold filter defaults on; this row is "hold" so it must be surfaced explicitly.
    // Awaited rather than fetched synchronously -- the checkbox only exists once the changes fetch
    // (a separate `useEffect` from the holdings one) has resolved and `deltaPhase` flips to loaded.
    const hideHold = await screen.findByLabelText(/Hide unchanged \(hold\) positions/);
    fireEvent.click(hideHold);

    // Located via the row's CUSIP, then scoped to that <tr> -- "Hold"/"Trim"/"Exit" are ambiguous
    // as plain text because the counts-strip above renders every action name as its own tile label
    // regardless of value, and this same CUSIP also appears in the separate Full holdings table
    // below. The CUSIP cell is unique within the Changes section's table body.
    const changesSection = (await screen.findByText("Changes since last filing")).closest(
      "section",
    ) as HTMLElement;
    const cusipCell = await within(changesSection).findByText("166764100");
    const row = cusipCell.closest("tr") as HTMLElement;
    expect(within(row).getByText("Hold")).toBeTruthy();
    // The value delta column carries its own "including price" framing in the header, not a claim
    // that anything was traded.
    expect(screen.getByText(/Value Δ \(incl\. price\)/)).toBeTruthy();
    // Never rendered as a trim/exit badge merely because the dollar value dropped.
    expect(within(row).queryByText("Trim")).toBeNull();
    expect(within(row).queryByText("Exit")).toBeNull();
  });

  it("labels an actual trim (shares down) distinctly from a hold, even when both show a value change", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      delta({
        changes: [
          change({
            cusip: "037833100",
            issuer: "APPLE INC",
            action: "trim",
            shares_before: "1000000",
            shares_after: "900000",
            shares_delta: "-100000",
            // A fraction of one, as the server sends it -- 900,000/1,000,000 is a tenth, so the
            // wire value is -0.10 and the cell must read -10.00%. Written as "-10.00" this
            // fixture disagreed with its own share counts by a factor of a hundred.
            shares_pct_change: "-0.10",
            value_before: "200000000",
            value_after: "185000000",
            value_delta: "-15000000",
          }),
        ],
        counts: { new: 0, exit: 0, add: 0, trim: 1, hold: 0 },
      }),
    );
    await renderInstitutions();

    // Located via the row's (unique) CUSIP rather than the "Trim" text alone, which the
    // counts-strip also renders as a tile label regardless of value -- see the Chevron-case test's
    // identical note above.
    const cusipCell = await screen.findByText("037833100");
    const row = cusipCell.closest("tr") as HTMLElement;
    expect(within(row).getByText("Trim")).toBeTruthy();
    expect(within(row).getByText(/-100,000/)).toBeTruthy();
    expect(within(row).getByText(/-10\.00%/)).toBeTruthy();
  });
});

describe("ticker nullability", () => {
  it("renders the issuer name as primary identity and no ticker badge when ticker is null", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ holdings: [holding({ ticker: null })] }));
    changesMock.mockResolvedValue(delta({ changes: [change({ ticker: null })] }));
    await renderInstitutions();

    const rows = await screen.findAllByText("CHEVRON CORP NEW");
    expect(rows.length).toBeGreaterThan(0);
    expect(screen.queryByText(/you own this/)).toBeNull();
    // The CUSIP is always shown -- the real identity when there is no ticker.
    expect(screen.getAllByText("166764100").length).toBeGreaterThan(0);
  });

  it("marks a row distinctly and offers a filter when ticker is non-null (an owned position)", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(
      snapshot({
        holdings: [
          holding({ ticker: "CVX" }),
          holding({ cusip: "037833100", issuer: "APPLE INC", ticker: null }),
        ],
      }),
    );
    changesMock.mockResolvedValue(delta({ changes: [change({ ticker: "CVX" })] }));
    await renderInstitutions();

    expect((await screen.findAllByText(/you own this/)).length).toBeGreaterThan(0);

    // Scoped to the Full holdings section rather than the whole page: the portfolio-shape row added
    // alongside `HoldingsPieChart` legitimately renders every holding's issuer name in its legend,
    // filter-independent by design (the pie shows the whole book's shape regardless of the "only
    // holdings I own" checkbox below it), so an unscoped `queryByText("APPLE INC")` would now find
    // that legend entry even after the Full holdings table itself has filtered the row away. This is
    // a real conflict the new layout introduces, not a loosening of what this test checks -- it still
    // asserts the exact same thing (the filtered table no longer shows Apple), just asked of the
    // right table.
    const holdingsSection = (await screen.findByText("Full holdings")).closest(
      "section",
    ) as HTMLElement;

    // Filter to only-owned in the Full holdings section -- narrows from 2 rows to 1.
    const holdingsFilters = screen.getAllByLabelText(/Only holdings I also own/);
    // Two "Only holdings I also own" checkboxes exist -- one per section. Use the last one, which
    // belongs to the Full holdings table (the changes one is asserted separately below).
    fireEvent.click(holdingsFilters[holdingsFilters.length - 1] as HTMLElement);

    expect(within(holdingsSection).queryByText("APPLE INC")).toBeNull();
    expect(within(holdingsSection).getAllByText("CHEVRON CORP NEW").length).toBeGreaterThan(0);
  });
});

describe("shares_pct_change null", () => {
  it("renders as the word 'new', never 0% or Infinity, for a brand-new position", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      delta({
        changes: [
          change({
            cusip: "88160R101",
            issuer: "TESLA INC",
            action: "new",
            shares_before: "0",
            shares_after: "50000",
            shares_delta: "50000",
            shares_pct_change: null,
            value_before: "0",
            value_after: "12000000",
            value_delta: "12000000",
          }),
        ],
        counts: { new: 1, exit: 0, add: 0, trim: 0, hold: 0 },
      }),
    );
    await renderInstitutions();

    expect(await screen.findByText("new")).toBeTruthy();
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(screen.queryByText(/Infinity|∞/)).toBeNull();
  });
});

describe("counts strip comes from the server", () => {
  it("keeps the server's total as the authority, never a client-side recount", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    // Only one row in `changes`, but `counts.new` claims 7. A client-side tally would show 1.
    changesMock.mockResolvedValue(
      delta({
        changes: [change({ action: "new", shares_pct_change: null })],
        counts: { new: 7, exit: 2, add: 3, trim: 1, hold: 40 },
      }),
    );
    await renderInstitutions();

    // "Hide unchanged (hold) positions" is on by default, so a filter is active from first paint
    // and every tile is qualified. The filer's own total is still the number after "of".
    expect(await screen.findByText("1 of 7")).toBeTruthy();
    expect(screen.getByText("0 of 40")).toBeTruthy();
  });

  it("qualifies every tile when a filter hides rows, rather than describing a table that is not there", async () => {
    // UAT run 11: with "only holdings I also own" checked, RENTECH's table read "No rows match the
    // current filters" while the strip above it still announced NEW 566 / TRIM 1489. The counts
    // described the filing; the table described the filter; nothing on screen said which was which.
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      delta({
        changes: [change({ action: "trim", ticker: null })],
        counts: { new: 566, exit: 639, add: 1079, trim: 1489, hold: 6 },
      }),
    );
    await renderInstitutions();

    // Both sections carry an "only holdings I also own" checkbox, so this must be scoped to the
    // Changes section rather than matched page-wide.
    const changesSection = (await screen.findByText("Changes since last filing")).closest(
      "section",
    ) as HTMLElement;
    fireEvent.click(within(changesSection).getByLabelText(/Only holdings I also own/));

    expect(await screen.findByText("No rows match the current filters.")).toBeTruthy();
    expect(screen.getByText("0 of 1489")).toBeTruthy();
    expect(screen.getByText(/Filters hide 3779 of 3779 positions; 0 shown/)).toBeTruthy();
  });

  it("shows the plain server tally, unqualified, when no row is actually hidden", async () => {
    // The qualifier keys on rows genuinely missing from the table, not on whether a checkbox is
    // ticked. QQQ's real diff has no `hold` rows at all, so the default "hide unchanged" filter
    // removes nothing -- and every tile read "95 of 95" beside "Filters are active: 104 of 104",
    // which is noise that teaches a reader to ignore the qualifier where it does matter.
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      delta({
        changes: [
          change({ cusip: "037833100", action: "new", shares_pct_change: null }),
          change({ cusip: "166764100", action: "trim", shares_pct_change: "-0.10" }),
        ],
        counts: { new: 1, exit: 0, add: 0, trim: 1, hold: 0 },
      }),
    );
    await renderInstitutions();

    // Nothing to hide: both rows survive the default filter, so the tiles stay unqualified.
    expect(await screen.findByText("No rows match the current filters.").catch(() => null)).toBeNull();
    expect(screen.queryByText(/Filters are hiding/)).toBeNull();
    const strip = document.querySelector(".inst-counts-strip") as HTMLElement;
    expect(within(strip).getAllByText("1").length).toBeGreaterThan(0);
    expect(within(strip).queryByText(/ of /)).toBeNull();
  });
});

describe("an unflagged row does not claim the user owns nothing", () => {
  it("states that matching is by CUSIP and that an unflagged row may still be owned", async () => {
    // Two independent UAT runs filed this. Apple is Berkshire's largest position at ~22% of the
    // disclosed book, the user holds AAPL, and it renders unflagged -- because only the Robinhood
    // adapter supplies CUSIPs at all.
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    // Now an `InfoNote`: the short summary ("Matched by CUSIP...") is always visible, and the full
    // reasoning ("no CUSIP match", "not non-ownership") lives in the disclosed body -- still present
    // in the DOM (an `InfoNote`/`<details>` never unmounts its children, only hides them visually),
    // so it is still found the same way, just via the note's containing element rather than one
    // `<span>`'s own `textContent`. `<em>` also splits the phrase across elements, so match the
    // container that holds the whole sentence rather than the emphasised fragment inside it.
    const caveats = await screen.findAllByText(/Matched by CUSIP/i);
    expect(caveats.length).toBeGreaterThan(0);
    const note = caveats[0]?.closest(".inst-owned-caveat");
    const text = note?.textContent ?? "";
    expect(text).toMatch(/no CUSIP match/i);
    expect(text).toMatch(/not non-ownership/i);
  });
});

describe("filing lag pill on the top disclaimer", () => {
  it("shows an amber 'Filing lag' pill beside the (now single) visible disclaimer text", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    const pill = screen.getByText("Filing lag");
    expect(pill.className).toMatch(/status-pill-warn/);
    // The caveat used to be said twice -- once as this pill's hover `title`, once again in the
    // paragraph right beside it. Kept once now, in the visible paragraph: the pill itself carries
    // no `detail` (and so no `title`) any more.
    expect(pill.getAttribute("title")).toBeNull();
    expect(screen.getAllByText(/45 days/).length).toBeGreaterThan(0);
  });
});

describe("Institutions <-> Consensus cross-link", () => {
  it("links to /consensus for a reader who wants the cross-fund view", async () => {
    // Rendered even before the funds fetch resolves -- a reader who wants the other page should
    // not have to wait for this page's own loading phase to find the door out.
    fundsMock.mockReturnValue(new Promise(() => {}));
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    const link = await screen.findByRole("link", { name: /what are all filers doing/i });
    expect(link.getAttribute("href")).toBe("/filers?tab=consensus");
  });
});

describe("13F/NPORT source note and provenance", () => {
  it("shows the 13F note and period/filed/accession for a 13F fund", async () => {
    fundsMock.mockResolvedValue({ funds: [fund({ source: "13F" })] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    expect((await screen.findAllByText(/US-listed equities only/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/2026-08-14/)).toBeTruthy(); // filed
    expect(screen.getAllByText(/0000950123-26-007654/).length).toBeGreaterThan(0); // accession
  });

  it("shows the NPORT note for an ETF fund, distinct from the 13F note", async () => {
    fundsMock.mockResolvedValue({
      funds: [fund({ key: "QQQ", name: "Invesco QQQ Trust", source: "NPORT", ticker: "QQQ" })],
    });
    holdingsMock.mockResolvedValue(snapshot({ fund: fund({ source: "NPORT" }) }));
    changesMock.mockResolvedValue(delta({ fund: fund({ source: "NPORT" }) }));
    await renderInstitutions();

    expect((await screen.findAllByText(/don't file 13F/)).length).toBeGreaterThan(0);
  });
});

describe("fund selector", () => {
  it("defaults to the first fund and re-fetches when a different one is chosen", async () => {
    const brk = fund({ key: "BRK", name: "Berkshire Hathaway Inc" });
    const qqq = fund({ key: "QQQ", name: "Invesco QQQ Trust", source: "NPORT", ticker: "QQQ" });
    fundsMock.mockResolvedValue({ funds: [brk, qqq] });
    holdingsMock.mockImplementation((key) =>
      Promise.resolve(snapshot({ fund: key === "BRK" ? brk : qqq })),
    );
    changesMock.mockImplementation((key) =>
      Promise.resolve(delta({ fund: key === "BRK" ? brk : qqq })),
    );
    await renderInstitutions();

    expect(holdingsMock).toHaveBeenCalledWith("BRK", undefined);

    fireEvent.change(screen.getByLabelText("Fund"), { target: { value: "QQQ" } });

    // The NPORT note appears in both the Changes and Holdings sections -- `findAllByText` rather
    // than `findByText`, which throws on more than one match.
    const notes = await screen.findAllByText(/don't file 13F/);
    expect(notes.length).toBeGreaterThan(0);
    expect(holdingsMock).toHaveBeenCalledWith("QQQ", undefined);
    expect(changesMock).toHaveBeenCalledWith("QQQ");
  });
});

describe("error and empty states", () => {
  it("shows a designed empty state, not a blank panel, when no funds are tracked", async () => {
    fundsMock.mockResolvedValue({ funds: [] });
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/No institutions or funds tracked yet/)).toBeTruthy();
  });

  it("surfaces a generic API error for the fund list instead of hanging", async () => {
    fundsMock.mockRejectedValue(new Error("network down"));
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Cannot reach the API/)).toBeTruthy();
  });

  it("does not treat an unrelated 404 on the fund list as an empty universe", async () => {
    fundsMock.mockRejectedValue(new ApiRequestError(404, "Not Found"));
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/API returned 404/)).toBeTruthy();
    expect(screen.queryByText(/No institutions or funds tracked yet/)).toBeNull();
  });

  it("treats the server's real 409 'only one filing' response as 'not enough history yet'", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    // Verbatim copy from `app/institutions/service.py`'s `InsufficientHistory`, on the status the
    // router actually returns. This test previously used a 404 and invented wording, and passed --
    // while the real endpoint's real response fell straight through to the red error state. The
    // fixture being a guess rather than the server's own text was the entire defect.
    changesMock.mockRejectedValue(
      new ApiRequestError(
        409,
        "'QQQ' has only 1 usable filing period on record -- at least 2 are required to compute a " +
          "change; check back after the next quarterly filing.",
      ),
    );
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/No comparison yet/)).toBeTruthy();
  });

  it("does not treat an unrelated 409 as 'not enough history'", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockRejectedValue(new ApiRequestError(409, "Conflict"));
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/API returned 409/)).toBeTruthy();
    expect(screen.queryByText(/No comparison yet/)).toBeNull();
  });

  it("shows a distinct, non-alarming message for a 503 from the SEC endpoint", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockRejectedValue(new ApiRequestError(503, "upstream unavailable"));
    render(
      <MemoryRouter>
        <Institutions />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/SEC endpoint unreachable/)).toBeTruthy();
    expect(screen.getByText(/nothing lost/i)).toBeTruthy();
  });

  it("shows an empty-holdings placeholder without erroring when a fund has no holdings on record", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ holdings: [] }));
    changesMock.mockResolvedValue(delta({ changes: [] }));
    await renderInstitutions();

    expect(await screen.findByText(/No holdings on record for this fund yet/)).toBeTruthy();
  });
});

describe("sortable holdings table", () => {
  it("re-orders rows when a sortable column header is clicked", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(
      snapshot({
        holdings: [
          holding({ cusip: "1", issuer: "ALPHA CO", value: "100", shares: "10", weight: "0.01" }),
          holding({ cusip: "2", issuer: "ZETA CO", value: "900", shares: "90", weight: "0.09" }),
        ],
      }),
    );
    changesMock.mockResolvedValue(delta({ changes: [] }));
    await renderInstitutions();

    // Scoped to the Full holdings section: the portfolio-shape row's pie legend also renders every
    // holding's issuer name (filter- and sort-independent, by design -- it always shows the whole
    // book), so an unscoped `findByText("ZETA CO")` is now ambiguous between the legend entry and
    // the table cell this test actually means to sort. Same real conflict as the "APPLE INC" case
    // above, same fix: scope to the section, not a weaker assertion.
    const holdingsSection = (await screen.findByText("Full holdings")).closest(
      "section",
    ) as HTMLElement;
    const table = within(holdingsSection).getByText("ZETA CO").closest("table") as HTMLTableElement;
    // Default sort is by value descending -- ZETA (900) before ALPHA (100).
    let issuerCells = within(table).getAllByText(/ALPHA CO|ZETA CO/);
    expect(issuerCells.map((el) => el.textContent)).toEqual(["ZETA CO", "ALPHA CO"]);

    fireEvent.click(within(table).getByText(/^Issuer/));
    issuerCells = within(table).getAllByText(/ALPHA CO|ZETA CO/);
    expect(issuerCells.map((el) => el.textContent)).toEqual(["ALPHA CO", "ZETA CO"]);
  });

  it("narrows Full holdings to issuers matching the FilterBar text query (1.10)", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(
      snapshot({
        holdings: [
          holding({ cusip: "1", issuer: "ALPHA CO", value: "100", shares: "10", weight: "0.01" }),
          holding({ cusip: "2", issuer: "ZETA CO", value: "900", shares: "90", weight: "0.09" }),
        ],
      }),
    );
    changesMock.mockResolvedValue(delta({ changes: [] }));
    await renderInstitutions();

    const holdingsSection = (await screen.findByText("Full holdings")).closest(
      "section",
    ) as HTMLElement;
    // Both rows present before any query is typed.
    expect(within(holdingsSection).getByText("ALPHA CO")).toBeTruthy();
    expect(within(holdingsSection).getByText("ZETA CO")).toBeTruthy();

    const query = within(holdingsSection).getByPlaceholderText(/filter by symbol/i);
    fireEvent.change(query, { target: { value: "zeta" } });

    expect(within(holdingsSection).queryByText("ALPHA CO")).toBeNull();
    expect(within(holdingsSection).getByText("ZETA CO")).toBeTruthy();
  });
});

describe("InstitutionsView (exported for Filers.tsx)", () => {
  it("renders the same content as the default page, minus its own <h1>/subtitle", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    render(
      <MemoryRouter>
        <InstitutionsView />
      </MemoryRouter>,
    );

    // The page banner ("Institutions" as an <h1>) is the default export's job now, not this
    // component's -- `Filers.tsx` supplies one shared banner instead. The content underneath (the
    // symbol lookup, the filing-lag disclaimer, the fund's own tables) is unchanged.
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(await screen.findByText(/Changes since last filing/)).toBeTruthy();
    expect(screen.getByText(/These are filings, not live positions/)).toBeTruthy();
  });
});

describe("a fund that changed size is not reported as a hundred decisions", () => {
  function tradedDelta(source: "13F" | "NPORT", traded: number, median: string | null) {
    return delta({
      fund: fund({ key: "QQQ", name: "Invesco QQQ Trust", source, ticker: "QQQ" }),
      counts: { new: 0, exit: 0, add: 0, trim: traded, hold: 0 },
      median_shares_pct_change: median,
      changes: [change({ action: "trim", shares_delta: "-1156434", shares_pct_change: "-0.0646" })],
    });
  }

  it("tells an ETF reader that a uniform move is the fund resizing, not stock picking", async () => {
    // QQQ's real Q4-2025 to Q1-2026 filing pair: 95 trims at a median of -6.07%. Read as ninety-five
    // sell decisions it is simply false -- the fund shrank and every position went with it.
    fundsMock.mockResolvedValue({ funds: [fund({ key: "QQQ", source: "NPORT", ticker: "QQQ" })] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(tradedDelta("NPORT", 95, "-0.0607"));
    await renderInstitutions();

    expect(await screen.findByText(/median share change was/)).toBeTruthy();
    expect(screen.getByText(/-6\.07%/)).toBeTruthy();
    expect(screen.getByText(/fund size or index changes, not a view on any name/)).toBeTruthy();
  });

  it("does not tell a 13F reader their manager's book merely resized", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(tradedDelta("13F", 13, "0.0365"));
    await renderInstitutions();

    expect(await screen.findByText(/Across the 13 positions/)).toBeTruthy();
    expect(screen.queryByText(/changing size or its index reconstituting/)).toBeNull();
  });

  it("says nothing at all when too few positions were traded for a median to mean anything", async () => {
    // Three trades have a median, but describing three decisions as "moved together" would be a
    // worse claim than making none.
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(tradedDelta("13F", 3, "-0.0500"));
    await renderInstitutions();

    expect(screen.queryByText(/median share change was/)).toBeNull();
  });

  it("says nothing when the filer traded nothing at all", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(tradedDelta("13F", 40, null));
    await renderInstitutions();

    expect(screen.queryByText(/median share change was/)).toBeNull();
  });
});

describe("both weight columns name their denominator, not just one of them", () => {
  // The recurring shape of defect in this project: a fix lands on one surface and not its twin.
  // It has happened to the drawdown card, the rule-editor placeholder, and the rule validator --
  // and then again here, where "Weight in filing" reached the Changes table while Full holdings
  // kept a bare "Weight". A reader who opened Full holdings first met the original ambiguity
  // untouched, with /portfolio's own differently-denominated "weight" one tab away.
  it("labels the weight column in the Changes table and in Full holdings alike", async () => {
    fundsMock.mockResolvedValue({ funds: [fund({ source: "13F" })] });
    holdingsMock.mockResolvedValue(snapshot());
    // A non-hold row, so the Changes table actually renders -- the default filter hides holds, and
    // a hidden table has no header to check.
    changesMock.mockResolvedValue(
      delta({
        changes: [change({ action: "trim", shares_pct_change: "-0.10" })],
        counts: { new: 0, exit: 0, add: 0, trim: 1, hold: 0 },
      }),
    );
    await renderInstitutions();

    const headers = await screen.findAllByText(/Weight in filing/);
    expect(headers.length).toBe(2);

    // Both must also carry the denominator, and for a 13F both must say it covers US-listed
    // equities only -- a 13F weight is a share of a slice, not of the manager's book.
    for (const header of headers) {
      const th = header.closest("th") as HTMLElement;
      expect(th.getAttribute("title")).toMatch(/US-listed equities only/i);
    }
  });

  it("says share-of-this-filing rather than the 13F wording for an ETF", async () => {
    fundsMock.mockResolvedValue({
      funds: [fund({ key: "QQQ", name: "Invesco QQQ Trust", source: "NPORT", ticker: "QQQ" })],
    });
    holdingsMock.mockResolvedValue(snapshot({ fund: fund({ key: "QQQ", source: "NPORT" }) }));
    changesMock.mockResolvedValue(
      delta({
        fund: fund({ key: "QQQ", source: "NPORT" }),
        changes: [change({ action: "trim", shares_pct_change: "-0.10" })],
        counts: { new: 0, exit: 0, add: 0, trim: 1, hold: 0 },
      }),
    );
    await renderInstitutions();

    const headers = await screen.findAllByText(/Weight in filing/);
    expect(headers.length).toBe(2);
    for (const header of headers) {
      const th = header.closest("th") as HTMLElement;
      expect(th.getAttribute("title")).toMatch(/total value disclosed in this filing/i);
      expect(th.getAttribute("title")).not.toMatch(/US-listed equities/i);
    }
  });

  it("also says the denominator visibly, in both tables, not only in the header's hover title", async () => {
    // The `title` attribute above is invisible on touch and unreachable by keyboard -- so the same
    // fact needs a visible home too, once per table (the Changes table and Full holdings each carry
    // their own copy, same as the header itself).
    fundsMock.mockResolvedValue({ funds: [fund({ source: "13F" })] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      delta({
        changes: [change({ action: "trim", shares_pct_change: "-0.10" })],
        counts: { new: 0, exit: 0, add: 0, trim: 1, hold: 0 },
      }),
    );
    await renderInstitutions();

    const captions = await screen.findAllByText(/US-listed equities only, not the manager's whole book/i);
    expect(captions.length).toBe(2);
  });
});

describe("a filer is findable by the person it is known for", () => {
  it("leads a 13F option with the principal, without dropping the firm that actually filed", async () => {
    fundsMock.mockResolvedValue({
      funds: [
        fund({
          key: "DUQUESNE",
          name: "Duquesne Family Office LLC",
          source: "13F",
          principal: "Stanley Druckenmiller",
        }),
      ],
    });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    const option = await screen.findByRole("option", { name: /Stanley Druckenmiller/ });
    // The firm is what filed, so it stays -- the person is a label on it, not a replacement.
    expect(option.textContent).toMatch(/Duquesne Family Office LLC/);
  });

  it("shows only the firm where naming a person would be a claim about the past", async () => {
    // Renaissance's founder died in 2024; attributing today's book to him would be false.
    fundsMock.mockResolvedValue({
      funds: [fund({ key: "RENTECH", name: "Renaissance Technologies LLC", principal: null })],
    });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    const option = await screen.findByRole("option", { name: /Renaissance Technologies LLC/ });
    expect(option.textContent).not.toMatch(/—/);
  });
});

describe("a rescaled filing says so", () => {
  it("discloses the ×1,000 correction rather than quietly applying it", async () => {
    // Duquesne's real 2026-06-30 filing states values in thousands despite the 2023 rule. Read
    // literally its book is $5.2m; it is $5.21bn. Correcting silently would be this application
    // asserting a figure the filer never disclosed, with nothing on screen to say so.
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ value_units_rescaled: true }));
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    expect(await screen.findByText(/Values rescaled ×1,000/)).toBeTruthy();
    expect(screen.getByText(/stated values in thousands despite 2023's whole-dollar rule/)).toBeTruthy();
  });

  it("says nothing at all when no correction was applied", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ value_units_rescaled: false }));
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    expect(screen.queryByText(/Values rescaled/)).toBeNull();
  });
});

describe("ticker badges are links to the ticker page", () => {
  it("renders the ticker badge as a real <a> pointed at /symbol/:symbol, not an inert span", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ holdings: [holding({ ticker: "CVX" })] }));
    changesMock.mockResolvedValue(delta({ changes: [change({ ticker: "CVX" })] }));
    await renderInstitutions();

    // One badge in the Changes table, one in Full holdings -- both must be real links, and both
    // must carry the exact URL `SymbolLookup`'s own navigation uses (`encodeURIComponent`-encoded).
    const links = await screen.findAllByRole("link", { name: /CVX/ });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      // The merged Symbol page is the canonical per-symbol route; IssuerCell links straight there
      // (the old /ticker path still resolves via a redirect, but the cell points at the direct route).
      expect(link.getAttribute("href")).toBe("/symbol/CVX");
    }
    // The "you own this" fact -- documented as the single most interesting thing this page can say
    // about a row -- must survive the swap from span to link.
    expect((await screen.findAllByText(/you own this/)).length).toBeGreaterThan(0);
  });
});

describe("portfolio shape row (pie + biggest recent moves)", () => {
  it("sits ahead of 'Changes since last filing' and 'Full holdings', not merged into either", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();
    await screen.findByText("Full holdings");

    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Portfolio shape", "Changes since last filing", "Full holdings"]);
  });

  it("collapses 'Changes since last filing' when its heading is clicked", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();
    await screen.findByText("Full holdings");

    const heading = screen.getByRole("heading", { level: 2, name: "Changes since last filing" });
    const details = heading.closest("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(true);

    fireEvent.click(heading.closest("summary") ?? heading);
    expect(details?.open).toBe(false);
  });

  it("also collapses 'Full holdings' when its heading is clicked, matching the Changes table", async () => {
    // Full holdings used to be the one section on this page not wrapped in `Collapsible` -- a long
    // snapshot table with no way to collapse it out of the way, unlike its sibling section right
    // above it.
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();
    await screen.findByText("Full holdings");

    const heading = screen.getByRole("heading", { level: 2, name: "Full holdings" });
    const details = heading.closest("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(true);

    fireEvent.click(heading.closest("summary") ?? heading);
    expect(details?.open).toBe(false);
  });

  it("feeds the pie from the snapshot and the moves panel from the delta, and wires a click in either through to the ticker page", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ holdings: [holding({ ticker: "CVX" })] }));
    changesMock.mockResolvedValue(delta({ changes: [change({ ticker: "CVX" })] }));
    await renderInstitutions();

    const pie = await screen.findByTestId("holdings-pie-chart");
    expect(within(pie).getByText("CHEVRON CORP NEW")).toBeTruthy();
    fireEvent.click(within(pie).getByText("CHEVRON CORP NEW"));
    expect(mockNavigate).toHaveBeenCalledWith("/symbol/CVX");

    const moves = await screen.findByTestId("recent-moves");
    fireEvent.click(within(moves).getByText("CHEVRON CORP NEW"));
    expect(mockNavigate).toHaveBeenCalledWith("/symbol/CVX");
  });

  it("puts the pie and moves cards inside one equal-height CardGrid", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    const pieCard = screen.getByTestId("inst-shape-pie-card");
    const movesCard = screen.getByTestId("inst-shape-moves-card");
    const grid = pieCard.closest(".card-grid");
    expect(grid).not.toBeNull();
    // Both halves of the row are tracks of the SAME grid -- the thing that actually makes their
    // bottom edges line up (`Card.css`'s `grid-auto-rows` docstring) -- not two independently-sized
    // panels that merely sit side by side.
    expect(grid?.contains(movesCard)).toBe(true);
    expect(pieCard.className).toContain("card");
    expect(movesCard.className).toContain("card");
  });

  it("reports a failed snapshot fetch honestly instead of rendering an empty pie that reads as 'holds nothing'", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockRejectedValue(new Error("network down"));
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();

    expect(await screen.findByText("Portfolio shape")).toBeTruthy();
    expect(screen.queryByTestId("holdings-pie-chart")).toBeNull();
    // The same "cannot reach the API" copy `HoldingsSection` shows for the identical failure --
    // one real error, not a second, silently different message for the pie's half of the row.
    expect(screen.getAllByText(/Cannot reach the API/).length).toBeGreaterThan(0);
  });
});

describe("table captions (EXP-15, WCAG 1.3.1)", () => {
  it("captions the Changes table with the fund name and the rows actually rendered", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot());
    changesMock.mockResolvedValue(
      // `action: "add"` rather than the fixture's default "hold" -- the hide-unchanged filter
      // defaults on, and a hidden "hold" row would leave this table's caption reading 0 rows.
      delta({ changes: [change({ action: "add" })], counts: { new: 0, exit: 0, add: 1, trim: 0, hold: 0 } }),
    );
    await renderInstitutions();
    // The Changes table only exists once `deltaPhase` flips from "loading" to "loaded" -- the
    // static "Changes since last filing" heading `renderInstitutions` waits on renders in every
    // phase. The hide-hold checkbox is scoped to the loaded table, matching the technique the
    // Chevron-case test above already uses to wait for the same transition.
    await screen.findByLabelText(/Hide unchanged \(hold\) positions/);

    const caption = screen.getByText("Changes since last filing for Berkshire Hathaway Inc, 1 rows");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption.className).toBe("visually-hidden");
  });

  it("captions the Full holdings table with the fund name and the rows actually rendered", async () => {
    fundsMock.mockResolvedValue({ funds: [fund()] });
    holdingsMock.mockResolvedValue(snapshot({ holdings: [holding(), holding({ cusip: "037833100" })] }));
    changesMock.mockResolvedValue(delta());
    await renderInstitutions();
    await screen.findByText("Full holdings");

    const caption = screen.getByText("Full holdings for Berkshire Hathaway Inc, 2 rows");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption.className).toBe("visually-hidden");
  });
});

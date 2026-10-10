/**
 * The Consensus page's honesty rules, at render level.
 *
 * Mirrors `Institutions.test.tsx`'s approach: the API module is stubbed at the module boundary
 * rather than `fetch` itself, since that is the seam the page actually depends on. Factory functions
 * build well-formed `ConsensusResponse`/`ConsensusRow`/`FundMove` values matching `@/api/consensus`'s
 * contract.
 *
 * Assertions use `.toBeTruthy()`/`queryBy...().toBeNull()` rather than jest-dom's
 * `toBeInTheDocument()`, matching this project's existing convention -- `@testing-library/jest-dom`
 * is not a dependency here (see `Institutions.test.tsx`/`WashSales.test.tsx`, neither of which use
 * it either).
 *
 * What these tests pin, matching the task's definition of done:
 *  - loading, loaded, empty and error states each render something distinct
 *  - switching Buying -> Selling changes the rows shown
 *  - `unchecked` funds render with their reasons, and the checked-count denominator ("2 of 3") is
 *    visible rather than buried
 *  - a `null` ticker renders the issuer without a broken link
 *  - each mover shows its own filing period (two movers on one CUSIP can carry different periods)
 *    and its own source (13F vs NPORT are never blended into one count)
 *  - the 13F/45-day, NPORT/60-day staleness caveat is present near the headline
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import {
  type ConsensusParams,
  type ConsensusResponse,
  type ConsensusRow,
  type FundMove,
} from "@/api/consensus";

const consensusMock =
  vi.fn<(params?: ConsensusParams, signal?: AbortSignal) => Promise<ConsensusResponse>>();

vi.mock("@/api/consensus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/consensus")>();
  return {
    ...actual,
    consensusApi: {
      ...actual.consensusApi,
      get: (params?: ConsensusParams, signal?: AbortSignal) => consensusMock(params, signal),
    },
  };
});

const { default: Consensus, ConsensusView } = await import("@/pages/Consensus");

function fundMove(overrides: Partial<FundMove> = {}): FundMove {
  return {
    key: "ARKK",
    name: "ARK Investment Management LLC",
    principal: "Cathie Wood",
    action: "add",
    weight_delta: "0.0210",
    shares_delta: "125000",
    period: "2026-06-30",
    source: "13F",
    ...overrides,
  };
}

function consensusRow(overrides: Partial<ConsensusRow> = {}): ConsensusRow {
  return {
    cusip: "67066G104",
    issuer: "NVIDIA CORP",
    ticker: "NVDA",
    buyer_count: 3,
    seller_count: 0,
    net_funds: 3,
    total_weight_delta: "0.0450",
    movers: [fundMove()],
    ...overrides,
  };
}

function appleSellRow(overrides: Partial<ConsensusRow> = {}): ConsensusRow {
  return consensusRow({
    cusip: "037833100",
    issuer: "APPLE INC",
    ticker: null,
    buyer_count: 0,
    seller_count: 2,
    total_weight_delta: "-0.0180",
    movers: [
      fundMove({
        key: "BRK",
        name: "Berkshire Hathaway Inc",
        principal: null,
        action: "trim",
        weight_delta: "-0.0180",
        shares_delta: "-500000",
        period: "2026-03-31",
        source: "13F",
      }),
    ],
    ...overrides,
  });
}

function consensusResponse(overrides: Partial<ConsensusResponse> = {}): ConsensusResponse {
  return {
    generated_at: "2026-08-24T12:00:00Z",
    as_of: "2026-06-30",
    checked: ["ARKK", "BRK", "QQQ"],
    unchecked: [],
    buys: [consensusRow()],
    sells: [appleSellRow()],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Consensus />
    </MemoryRouter>,
  );
}

describe("Consensus page", () => {
  beforeEach(() => {
    consensusMock.mockReset();
  });

  it("renders a table-shaped Skeleton during the cold-cache walk, not a bare 'Loading…' line", async () => {
    consensusMock.mockReturnValue(new Promise(() => {}));
    const { container } = renderPage();

    // The skeleton itself: placeholder row blocks in the ranked table's rough shape, not a single
    // collapsed line -- see `Skeleton.tsx`'s own docstring for why a bare "Loading…" causes a
    // layout jump this avoids.
    expect(container.querySelector(".skeleton-rows")).toBeTruthy();
    expect(container.querySelectorAll(".skeleton-block").length).toBeGreaterThan(1);

    // The accessible live-region text names what is loading ("filers"), which the old plain-text
    // placeholder never did.
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("Loading filers…");

    // The literal copy this replaces is gone from the loading phase.
    expect(screen.queryByText(/^loading consensus…$/i)).toBeNull();
  });

  it("renders the loaded state and switching Buying -> Selling changes the rows", async () => {
    consensusMock.mockResolvedValue(consensusResponse());
    renderPage();

    expect(await screen.findByText("NVIDIA CORP")).toBeTruthy();
    expect(screen.queryByText("APPLE INC")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Selling" }));

    expect(await screen.findByText("APPLE INC")).toBeTruthy();
    expect(screen.queryByText("NVIDIA CORP")).toBeNull();
  });

  it("renders an empty state distinct from loading and error", async () => {
    consensusMock.mockResolvedValue(consensusResponse({ buys: [], sells: [] }));
    renderPage();

    expect(await screen.findByText(/no consensus moves this run/i)).toBeTruthy();
    expect(screen.queryByText(/loading consensus/i)).toBeNull();
  });

  it("renders an error state distinct from loading and empty", async () => {
    consensusMock.mockRejectedValue(new ApiRequestError(500, "boom"));
    renderPage();

    expect(await screen.findByText(/API returned 500/)).toBeTruthy();
    expect(screen.queryByText(/loading consensus/i)).toBeNull();
    expect(screen.queryByText(/no consensus moves/i)).toBeNull();
  });

  it("renders unchecked funds with their reasons and a checked-count denominator", async () => {
    consensusMock.mockResolvedValue(
      consensusResponse({
        checked: ["ARKK", "QQQ"],
        unchecked: [
          { key: "BRK", name: "Berkshire Hathaway Inc", reason: "EDGAR request timed out" },
        ],
      }),
    );
    const { container } = renderPage();

    // The denominator: 2 funds actually checked out of a 3-fund tracked universe.
    expect(await screen.findByText("2 of 3")).toBeTruthy();
    expect(screen.getByText(/not comparable, excluded below/i)).toBeTruthy();

    // The unchecked fund and its reason are on screen, not only implied by the count.
    expect(screen.getByText("Berkshire Hathaway Inc")).toBeTruthy();
    expect(screen.getByText(/EDGAR request timed out/)).toBeTruthy();

    // The ranked table repeats the same "checked" denominator so it is visible without scrolling
    // back up to the provenance strip.
    const tableDenominator = container.querySelector(".consensus-denominator");
    expect(tableDenominator?.textContent).toMatch(/out of 2 funds checked this run/);
  });

  it("renders a null ticker as issuer text with no broken link", async () => {
    consensusMock.mockResolvedValue(consensusResponse());
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Selling" }));

    expect(await screen.findByText("APPLE INC")).toBeTruthy();
    // No ticker badge/link exists anywhere for the Apple row -- its `ticker` is null.
    expect(screen.queryByRole("link", { name: /open .* page/i })).toBeNull();
  });

  it("shows each mover's own filing period and its own source, unblended", async () => {
    consensusMock.mockResolvedValue(
      consensusResponse({
        buys: [
          consensusRow({
            movers: [
              fundMove({ key: "ARKK", period: "2026-06-30", source: "13F" }),
              fundMove({
                key: "QQQ",
                name: "Invesco QQQ Trust",
                principal: null,
                period: "2026-03-31",
                source: "NPORT",
              }),
            ],
          }),
        ],
      }),
    );
    renderPage();

    expect(await screen.findByText("NVIDIA CORP")).toBeTruthy();

    // Two movers on the same CUSIP, two different filing periods -- both visible, never collapsed
    // into one shared date for the row.
    expect(screen.getByText("as of 2026-06-30")).toBeTruthy();
    expect(screen.getByText("as of 2026-03-31")).toBeTruthy();

    // Each mover's own regime is labelled, not folded into one undifferentiated count.
    expect(screen.getByText("13F")).toBeTruthy();
    expect(screen.getByText("NPORT")).toBeTruthy();
  });

  it("states the 13F/NPORT staleness caveat near the headline", async () => {
    consensusMock.mockResolvedValue(consensusResponse());
    renderPage();

    expect(await screen.findByText(/these are filings, not live trading activity/i)).toBeTruthy();
    expect(screen.getByText(/45 days/)).toBeTruthy();
    expect(screen.getByText(/60 days/)).toBeTruthy();
  });

  it("shows an amber 'Filing lag' pill on the staleness caveat, carrying the disclaimer body as its detail", async () => {
    consensusMock.mockResolvedValue(consensusResponse());
    renderPage();

    await screen.findByText(/these are filings, not live trading activity/i);
    const pill = screen.getByText("Filing lag");
    expect(pill.className).toMatch(/status-pill-warn/);
    expect(pill.getAttribute("title")).toMatch(/45 days/);
  });

  it("links to /filers for a reader who wants one filer instead of the cross-fund ranking", async () => {
    // Rendered before the fetch resolves too -- a reader who wants the other page should not have
    // to wait out the loading phase to find the door out.
    //
    // `/filers`, not the old `/institutions`: that path still resolves, but only as a redirect, and
    // an in-app link that costs the reader a hop is one that breaks when the redirect is retired.
    consensusMock.mockReturnValue(new Promise(() => {}));
    renderPage();

    const link = await screen.findByRole("link", { name: /look up a filer/i });
    expect(link.getAttribute("href")).toBe("/filers");
  });

  it("narrows the ranked table to issuers/tickers matching the FilterBar text query (1.10), keeping the original rank", async () => {
    consensusMock.mockResolvedValue(
      consensusResponse({
        buys: [
          consensusRow(), // rank 1: NVIDIA CORP / NVDA
          consensusRow({
            cusip: "594918104",
            issuer: "MICROSOFT CORP",
            ticker: "MSFT",
            movers: [fundMove({ key: "ARKK" })],
          }), // rank 2
        ],
      }),
    );
    renderPage();

    expect(await screen.findByText("NVIDIA CORP")).toBeTruthy();
    expect(screen.getByText("MICROSOFT CORP")).toBeTruthy();

    const query = screen.getByPlaceholderText(/filter by symbol/i);
    fireEvent.change(query, { target: { value: "msft" } });

    expect(screen.queryByText("NVIDIA CORP")).toBeNull();
    expect(screen.getByText("MICROSOFT CORP")).toBeTruthy();
    // Still ranked "2", its position in the FULL list -- filtering to one row must not renumber it
    // to "1", which would silently change what the rank column means.
    expect(screen.getByRole("cell", { name: "2" })).toBeTruthy();
  });

  it("shows a distinct 'nothing matches' message when the FilterBar query matches no row", async () => {
    consensusMock.mockResolvedValue(consensusResponse());
    renderPage();

    expect(await screen.findByText("NVIDIA CORP")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/filter by symbol/i), {
      target: { value: "no-such-issuer" },
    });

    expect(screen.queryByText("NVIDIA CORP")).toBeNull();
    expect(screen.getByText(/no transactions match these filters/i)).toBeTruthy();
  });
});

describe("table caption (EXP-15, WCAG 1.3.1)", () => {
  it("captions the ranked table with the current heading and the rows actually rendered, and swaps on Buying/Selling", async () => {
    consensusMock.mockResolvedValue(
      consensusResponse({
        buys: [consensusRow(), consensusRow({ cusip: "AAA", issuer: "MICROSOFT CORP", ticker: "MSFT" })],
      }),
    );
    renderPage();
    await screen.findByText("NVIDIA CORP");

    let caption = screen.getByText("Most bought, 2 rows");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption.className).toBe("visually-hidden");

    fireEvent.click(screen.getByRole("tab", { name: "Selling" }));
    await screen.findByText("APPLE INC");
    caption = screen.getByText("Most sold, 1 rows");
    expect(caption.tagName).toBe("CAPTION");
  });
});

describe("ConsensusView (exported for Filers.tsx)", () => {
  it("renders the same content as the default page, minus its own <h1>/subtitle", async () => {
    consensusMock.mockResolvedValue(consensusResponse());
    render(
      <MemoryRouter>
        <ConsensusView />
      </MemoryRouter>,
    );

    // The page banner ("Consensus" as an <h1>) is the default export's job now, not this
    // component's -- `Filers.tsx` supplies one shared banner instead. The content underneath (the
    // staleness disclaimer, the ranked tables) is unchanged.
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(await screen.findByText("NVIDIA CORP")).toBeTruthy();
    expect(screen.getByText(/these are filings, not live trading activity/i)).toBeTruthy();
  });
});

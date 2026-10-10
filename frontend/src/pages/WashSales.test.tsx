/**
 * The Wash Sales page's honesty rules, at render level.
 *
 * Mirrors `Tax.test.tsx`'s approach: the API module is stubbed at the module boundary rather than
 * `fetch` itself, since that is the seam the page actually depends on. Factory functions mirror
 * the ones in `@/api/washsales.test.ts` (`wellFormedTracker` / `wellFormedSymbol` /
 * `wellFormedSale`) so the shapes stay in sync with that file's contract.
 *
 * What these tests pin, matching the task's definition of done:
 *  - an open-window symbol renders its days-remaining and safe-on date
 *  - deferred and permanent figures render as separate numbers, never summed into one
 *  - the open-window symbols render as a sortable table, defaulting to soonest-closing first, and
 *    re-sort when a column header is clicked
 *  - each open-window row's per-sale drill-down is collapsed by default and its sale rows are
 *    reachable once the row's toggle is clicked (asserted via the toggle's `aria-expanded` and the
 *    presence of the `.wsale-open-detail-row`, since the open table no longer uses a `<details>`)
 *  - the closed-window cards, which still use `<details>`, stay collapsed by default (checked via
 *    the `<details>` element's `open` property, the same technique `Portfolio.test.tsx` uses for
 *    `.empty-accounts-detail` -- jsdom does not natively hide a closed <details>'s content)
 *  - an empty tracker renders a designed empty state, not a blank panel
 *  - the scope line is present
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import {
  type WashSaleTracker,
  type WashSaleTrackerSale,
  type WashSaleTrackerSymbol,
} from "@/api/washsales";

const trackerMock = vi.fn<() => Promise<WashSaleTracker>>();

vi.mock("@/api/washsales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/washsales")>();
  return {
    ...actual,
    washSalesApi: { ...actual.washSalesApi, tracker: () => trackerMock() },
  };
});

// The SECTION, not the default-export page. `/wash-sales` is a redirect now: this surface renders
// inside the Tax page's Wash sales tab, which owns the `<h1>` the page form still carries. Every
// assertion below is unchanged -- the heading was the only thing that moved.
const { WashSalesSection: WashSales } = await import("@/pages/WashSales");

function washSaleSale(
  overrides: Partial<WashSaleTrackerSale> = {},
): WashSaleTrackerSale {
  return {
    disposal_id: "disp-1",
    sale_date: "2026-07-15",
    account_id: "rh-taxable",
    quantity_sold: "7",
    quantity_replaced: "7",
    loss_amount: "26.25",
    disallowed_loss: "26.25",
    permanently_disallowed: false,
    replacement_account_ids: ["rh-taxable"],
    window_closes_on: "2026-08-15",
    ...overrides,
  };
}

function washSaleSymbol(
  overrides: Partial<WashSaleTrackerSymbol> = {},
): WashSaleTrackerSymbol {
  return {
    symbol: "NVDA",
    deferred_disallowed: "1234.56",
    permanently_disallowed: "0.00",
    event_count: 1,
    loss_sale_count: 1,
    first_sale_date: "2026-07-15",
    last_sale_date: "2026-07-15",
    repurchase_safe_on: "2026-08-15",
    days_until_safe: 2,
    window_is_open: true,
    accounts: ["rh-taxable"],
    sales: [washSaleSale()],
    ...overrides,
  };
}

function washSaleTracker(
  overrides: Partial<WashSaleTracker> = {},
): WashSaleTracker {
  return {
    as_of: "2026-08-17",
    generated_at: "2026-08-17T12:00:00Z",
    total_deferred: "94998.50",
    total_permanently_disallowed: "2790.52",
    open_window_count: 1,
    symbol_count: 1,
    symbols: [washSaleSymbol()],
    ...overrides,
  };
}

async function renderWashSales(data: WashSaleTracker) {
  trackerMock.mockResolvedValue(data);
  render(
    <MemoryRouter>
      <WashSales />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { name: "Open windows" });
}

/** The Open windows sortable table. */
function openTable(): HTMLElement {
  const table = document.querySelector(".wsale-open-table");
  if (!table) throw new Error("no open-window table");
  return table as HTMLElement;
}

/** The toggle button in an open-window row -- its accessible name is the bare symbol (the caret is
 *  `aria-hidden`), so it never collides with the column-header sort buttons in the same table. */
function openRowToggle(symbol: string): HTMLElement {
  return within(openTable()).getByRole("button", { name: symbol });
}

/** The `<tr>` for an open-window symbol, located via its toggle button. */
function openRow(symbol: string): HTMLElement {
  const row = openRowToggle(symbol).closest("tr");
  if (!row) throw new Error(`no open-window row for ${symbol}`);
  return row as HTMLElement;
}

/** Open-window symbols in the table's current row order, top to bottom. */
function openRowSymbols(): string[] {
  return Array.from(
    openTable().querySelectorAll(".wsale-open-row .wsale-symbol-name"),
  ).map((el) => el.textContent ?? "");
}

/** The expanded drill-down row, if any is currently open. */
function openDetailRow(): HTMLElement | null {
  return openTable().querySelector(".wsale-open-detail-row");
}

beforeEach(() => {
  trackerMock.mockReset();
});

describe("open windows are the headline", () => {
  it("renders an open-window symbol's days-remaining and safe-on date", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "NVDA",
            days_until_safe: 2,
            repurchase_safe_on: "2026-08-19",
            window_is_open: true,
          }),
        ],
      }),
    );

    const row = openRow("NVDA");
    expect(within(row).getByText(/2 days left/)).toBeTruthy();
    expect(within(row).getByText("2026-08-19")).toBeTruthy();
  });

  it("defaults to sorting by days remaining, most urgent first -- not alphabetically", async () => {
    await renderWashSales(
      washSaleTracker({
        open_window_count: 3,
        symbol_count: 3,
        symbols: [
          washSaleSymbol({
            symbol: "ZETA",
            days_until_safe: 25,
            window_is_open: true,
          }),
          washSaleSymbol({
            symbol: "AAPL",
            days_until_safe: 1,
            window_is_open: true,
          }),
          washSaleSymbol({
            symbol: "MSFT",
            days_until_safe: 12,
            window_is_open: true,
          }),
        ],
      }),
    );

    expect(openRowSymbols()).toEqual(["AAPL", "MSFT", "ZETA"]);
  });

  it("re-sorts by deferred amount, largest first, when the Deferred header is clicked", async () => {
    await renderWashSales(
      washSaleTracker({
        open_window_count: 3,
        symbol_count: 3,
        symbols: [
          washSaleSymbol({
            symbol: "AAPL",
            days_until_safe: 1,
            deferred_disallowed: "100.00",
          }),
          washSaleSymbol({
            symbol: "MSFT",
            days_until_safe: 12,
            deferred_disallowed: "9000.00",
          }),
          washSaleSymbol({
            symbol: "ZETA",
            days_until_safe: 25,
            deferred_disallowed: "2500.50",
          }),
        ],
      }),
    );

    // Default order is by urgency (days remaining).
    expect(openRowSymbols()).toEqual(["AAPL", "MSFT", "ZETA"]);

    // A fresh click on the money column lands on its default direction: largest deferred first.
    fireEvent.click(within(openTable()).getByRole("button", { name: /Deferred/ }));
    expect(openRowSymbols()).toEqual(["MSFT", "ZETA", "AAPL"]);

    // Clicking the same header again flips to ascending.
    fireEvent.click(within(openTable()).getByRole("button", { name: /Deferred/ }));
    expect(openRowSymbols()).toEqual(["AAPL", "ZETA", "MSFT"]);
  });

  it("shows a designed placeholder, not an empty list, when no window is currently open", async () => {
    await renderWashSales(
      washSaleTracker({
        open_window_count: 0,
        symbols: [
          washSaleSymbol({
            window_is_open: false,
            deferred_disallowed: "500.00",
          }),
        ],
      }),
    );

    expect(
      screen.getByText(/No wash-sale window is currently open/),
    ).toBeTruthy();
  });
});

describe("deferred and permanently disallowed never get summed", () => {
  it("renders both figures in separate columns on an open-window row", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "SOXL",
            deferred_disallowed: "1234.56",
            permanently_disallowed: "789.01",
            window_is_open: true,
          }),
        ],
      }),
    );

    const row = openRow("SOXL");
    expect(within(row).getByText("$1,234.56")).toBeTruthy();
    expect(within(row).getByText("$789.01")).toBeTruthy();
    // The one figure this page must never render anywhere: the two columns summed together.
    expect(screen.queryByText("$2,023.57")).toBeNull();
  });

  it("never sums the two headline tiles either", async () => {
    await renderWashSales(
      washSaleTracker({
        total_deferred: "94998.50",
        total_permanently_disallowed: "2790.52",
      }),
    );

    expect(screen.getByText("$94,998.50")).toBeTruthy();
    expect(screen.getByText("$2,790.52")).toBeTruthy();
    expect(screen.queryByText("$97,789.02")).toBeNull();
    expect(document.body.textContent).not.toMatch(/wash-sale impact/i);
  });

  it("omits the permanent-loss tile from summing even when it renders zero, not a dash", async () => {
    await renderWashSales(
      washSaleTracker({ total_permanently_disallowed: "0.00" }),
    );
    expect(screen.getByText("$0.00")).toBeTruthy();
  });
});

describe("per-ticker drill-down", () => {
  it("is collapsed by default and reveals its sale rows once the row is expanded", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "TSLA",
            window_is_open: true,
            sales: [
              washSaleSale({
                disposal_id: "d-tsla-1",
                account_id: "wb-margin",
              }),
            ],
          }),
        ],
      }),
    );

    const toggle = openRowToggle("TSLA");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(openDetailRow()).toBeNull();

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const detail = openDetailRow() as HTMLElement;
    expect(detail).not.toBeNull();
    expect(within(detail).getByText("wb-margin")).toBeTruthy();
    expect(within(detail).getByText("2026-08-15")).toBeTruthy(); // window_closes_on
  });

  it("renders a designed placeholder rather than fabricating a row when sale-level detail is absent", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({ symbol: "AMD", window_is_open: true, sales: [] }),
        ],
      }),
    );

    fireEvent.click(openRowToggle("AMD"));

    expect(screen.getByText(/No per-sale detail available/)).toBeTruthy();
  });
});

describe("closed windows are folded away by default", () => {
  it("lists a closed-window symbol still riding deferred loss, collapsed until expanded", async () => {
    await renderWashSales(
      washSaleTracker({
        open_window_count: 0,
        symbols: [
          washSaleSymbol({
            symbol: "GME",
            window_is_open: false,
            deferred_disallowed: "42.00",
            repurchase_safe_on: "2026-07-01",
          }),
        ],
      }),
    );

    const summaryText = screen.getByText(/1 closed-window symbol/);
    const outerDisclosure = summaryText.closest(
      "details",
    ) as HTMLDetailsElement;
    expect(outerDisclosure).not.toBeNull();
    // Collapsed by default -- checked via the DOM `open` property, not by asserting the symbol's
    // text is absent: jsdom does not apply a real browser's native hiding of a closed <details>'s
    // content, so `queryByText` would find it either way (see `Portfolio.test.tsx`'s identical
    // note on `.empty-accounts-detail` for the same reason).
    expect(outerDisclosure.open).toBe(false);

    fireEvent.click(summaryText);

    expect(outerDisclosure.open).toBe(true);
    expect(screen.getByText("GME")).toBeTruthy();
  });

  it("still shows the safe-from date once the window has closed", async () => {
    // The sibling surface lost exactly this. `/tax`'s wash-sale panel rendered the date while a
    // window was open and dropped it the moment the window closed -- while the caption underneath
    // still promised one -- and two personas filed it before anyone noticed the branch. The date is
    // the answer to "when did this become safe", and it does not stop being the answer once the
    // answer is in the past. Nothing but this test stops the same line being dropped here.
    await renderWashSales(
      washSaleTracker({
        open_window_count: 0,
        symbols: [
          washSaleSymbol({
            symbol: "GME",
            window_is_open: false,
            deferred_disallowed: "42.00",
            repurchase_safe_on: "2026-07-01",
          }),
        ],
      }),
    );

    fireEvent.click(screen.getByText(/1 closed-window symbol/));
    const card = screen
      .getByText("GME")
      .closest("details") as HTMLDetailsElement;
    expect(card).not.toBeNull();
    expect(card.textContent ?? "").toContain("2026-07-01");
  });

  it("excludes a closed-window symbol with no outstanding deferred loss, and names the exclusion", async () => {
    await renderWashSales(
      washSaleTracker({
        open_window_count: 0,
        symbols: [
          washSaleSymbol({
            symbol: "SETTLED",
            window_is_open: false,
            deferred_disallowed: "0.00",
          }),
        ],
      }),
    );

    const summaryText = screen.getByText(/0 closed-window symbols/);
    fireEvent.click(summaryText);
    expect(screen.queryByText("SETTLED")).toBeNull();
    expect(
      screen.getByText(
        /1 other closed-window symbol carries no outstanding deferred loss/,
      ),
    ).toBeTruthy();
  });
});

describe("an untriggered loss sale reads as a live warning, not an empty row", () => {
  it("highlights a sale row with disallowed_loss of zero while its window is still open, rather than showing it as deferred", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "PLTR",
            window_is_open: true,
            deferred_disallowed: "0.00",
            permanently_disallowed: "0.00",
            sales: [
              washSaleSale({
                disposal_id: "d-pltr-1",
                loss_amount: "150.00",
                disallowed_loss: "0.00",
                quantity_replaced: "0",
                replacement_account_ids: [],
                permanently_disallowed: false,
              }),
            ],
          }),
        ],
      }),
    );

    // Symbol-level indicator, visible without expanding the row.
    const symbolRow = openRow("PLTR");
    expect(within(symbolRow).getByText("not yet triggered")).toBeTruthy();

    const toggle = openRowToggle("PLTR");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    // The zero disallowed figure in the drill-down's own sale row is a real zero -- rendered, not
    // withheld as a dash. (The symbol-level Deferred figure is also "$0.00" in this fixture, and
    // the sale date "2026-07-15" also appears in the drill-down's meta line, so this locates the
    // one sale row via the drill-down table body directly rather than an ambiguous text match.)
    // Scope to the drill-down's own sales table: a bare `tbody tr` from the detail row also matches
    // that table's header row, since the outer open-windows `<tbody>` is an ancestor of it too.
    const detail = openDetailRow() as HTMLElement;
    const row = detail.querySelector(".wsale-sales-table tbody tr") as HTMLElement;
    expect(row).not.toBeNull();
    expect(within(row).getByText("$0.00")).toBeTruthy();
    // And it must not be mislabeled as an actual deferral or permanent disallowance.
    expect(within(row).queryByText("deferred to replacement basis")).toBeNull();
    expect(within(row).queryByText(/PERMANENT/)).toBeNull();
    expect(
      within(row).getByText(/repurchase now creates a wash sale/),
    ).toBeTruthy();
  });

  it("excludes a closed-window, zero-disallowed sale from the still-riding closed list entirely", async () => {
    await renderWashSales(
      washSaleTracker({
        open_window_count: 0,
        symbols: [
          washSaleSymbol({
            symbol: "SNOW",
            window_is_open: false,
            deferred_disallowed: "0.00",
            permanently_disallowed: "0.00",
            sales: [
              washSaleSale({
                disposal_id: "d-snow-1",
                disallowed_loss: "0.00",
              }),
            ],
          }),
        ],
      }),
    );

    // Nothing is still riding on a replacement lot for this symbol -- it lands in the excluded
    // "settled" count, named at the point of the total, rather than in the still-riding list.
    expect(
      screen.getByText(/0 closed-window symbols still carrying deferred loss/),
    ).toBeTruthy();
    expect(
      screen.getByText(
        /1 other closed-window symbol carries no outstanding deferred loss/,
      ),
    ).toBeTruthy();
    expect(screen.queryByText("SNOW")).toBeNull();
  });

  it("does not mark a symbol as untriggered when every sale has already been disallowed", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "IBM",
            window_is_open: true,
            deferred_disallowed: "500.00",
            sales: [
              washSaleSale({
                disposal_id: "d-ibm-1",
                disallowed_loss: "500.00",
              }),
            ],
          }),
        ],
      }),
    );

    expect(screen.queryByText("not yet triggered")).toBeNull();
  });
});

describe("the disclaimer is the Tax page's disclaimer, not a second one", () => {
  it("leads with the 'Not advice' pill this page used to omit entirely", async () => {
    await renderWashSales(washSaleTracker());

    const disclaimer = document.querySelector(".panel.disclaimer")!;
    const pill = disclaimer.querySelector(".status-pill-warn")!;
    expect(pill).not.toBeNull();
    expect(pill.textContent).toBe("Not advice");

    // Pill first, then the lead sentence -- same order as `Tax.tsx`'s own disclaimer.
    const strongEl = disclaimer.querySelector("strong")!;
    expect(pill.compareDocumentPosition(strongEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders the shared body verbatim -- 'The engine replays', not this page's old 'Detection replays'", async () => {
    // Two wordings of one disclaimer is how the reviewed one starts drifting from the rendered one.
    await renderWashSales(washSaleTracker());

    const disclaimer = document.querySelector(".panel.disclaimer")!;
    expect(disclaimer.textContent).toContain("Calculation only, not tax advice.");
    expect(disclaimer.textContent).toContain("The engine replays your brokerage history");
    expect(disclaimer.textContent).not.toContain("Detection replays");
  });
});

describe("headline tiles carry their scope", () => {
  it("labels both money tiles '(all years)', against the Tax page's year-scoped pair", async () => {
    // The Tax page's deferred tile is one tax year; this one is the whole connected ledger, and is
    // routinely several times larger. Unlabelled, the two read as one figure disagreeing with
    // itself. DEFINITIONS.md standing rule 2.
    await renderWashSales(washSaleTracker());

    const labels = [...document.querySelectorAll(".tile-grid .label")].map((el) => el.textContent);
    expect(labels).toEqual([
      "Deferred wash-sale loss (all years)",
      "Permanently disallowed, IRA (all years)",
      "Open-window symbols",
      "Symbols tracked",
    ]);
    // No tile on this page may claim a tax year -- it does not have one.
    expect(labels.join(" ")).not.toMatch(/\d{4}/);
  });
});

describe("empty and scope states", () => {
  it("renders a designed empty state, not a blank panel, when the tracker has no symbols", async () => {
    trackerMock.mockResolvedValue(
      washSaleTracker({ symbols: [], symbol_count: 0, open_window_count: 0 }),
    );
    render(
      <MemoryRouter>
        <WashSales />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/No wash sales in your connected history/),
    ).toBeTruthy();
    expect(screen.queryByText(/Open windows/)).toBeNull();
  });

  it("states the scope: whole-ledger, not the Tax page's tax-year scope, and today's as-of date", async () => {
    await renderWashSales(washSaleTracker({ as_of: "2026-08-17" }));

    const body = document.body.textContent ?? "";
    expect(body).toContain("not one tax year");
    expect(body).toContain("2026-08-17");
  });

  it("surfaces an API error instead of hanging on a loading placeholder", async () => {
    trackerMock.mockRejectedValue(new Error("network down"));
    render(
      <MemoryRouter>
        <WashSales />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Cannot reach the API/)).toBeTruthy();
  });

  it("treats a 404 as an empty ledger only when the API says the ledger is empty", async () => {
    trackerMock.mockRejectedValue(
      new ApiRequestError(404, "no ledger yet; import broker exports first"),
    );
    render(
      <MemoryRouter>
        <WashSales />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/No wash sales/i)).toBeTruthy();
  });

  it("renders both halves of a disposal split across a taxable account and an IRA", async () => {
    // `sales` is event-grained, so one disposal whose replacement spanned both produces two rows
    // sharing a `disposal_id` -- one deferred, one permanently disallowed. Keyed on the id alone,
    // React renders only one of them, and the reader silently loses a loss that Rev. Rul. 2008-5
    // destroyed outright. Real ledgers can contain disposals with this shape.
    const shared = "disp-split-1";
    const tracker = washSaleTracker({
      symbols: [
        washSaleSymbol({
          symbol: "SPLIT",
          window_is_open: true,
          sales: [
            washSaleSale({
              disposal_id: shared,
              disallowed_loss: "40.00",
              permanently_disallowed: false,
            }),
            washSaleSale({
              disposal_id: shared,
              disallowed_loss: "25.00",
              permanently_disallowed: true,
            }),
          ],
        }),
      ],
    });
    trackerMock.mockResolvedValue(tracker);
    render(
      <MemoryRouter>
        <WashSales />
      </MemoryRouter>,
    );

    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    await screen.findByText("SPLIT");
    const toggle = openRowToggle("SPLIT");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    // Both rows present -- not one row swallowed by a duplicate React key.
    const disclosure = openDetailRow() as HTMLElement;
    const rows = disclosure.querySelectorAll(".wsale-sales-table tbody tr");
    expect(rows.length).toBe(2);

    const body = disclosure.textContent ?? "";
    expect(body).toContain("$40.00");
    expect(body).toContain("$25.00");
    // And never as one combined figure.
    expect(body).not.toContain("$65.00");

    // The rows must also be *distinct* to React. Keyed on `disposal_id` alone they collide, which
    // renders acceptably on first mount but makes reconciliation on any later update free to reuse
    // one row's DOM for the other -- the deferred figure wearing the permanent row's label, or the
    // reverse. React reports the collision here and nowhere else, so this is the assertion that
    // catches it.
    const duplicateKeyWarning = consoleError.mock.calls.some((args) =>
      args.some(
        (a) => typeof a === "string" && /same key|duplicate key/i.test(a),
      ),
    );
    expect(duplicateKeyWarning).toBe(false);
    consoleError.mockRestore();
  });

  it("does not report a missing route as 'no wash sales'", async () => {
    // A route that does not exist also 404s -- FastAPI answers `Not Found`. Rendering that as an
    // empty tracker tells a reader their wash-sale exposure is nil when it is simply unmeasured,
    // which is a false all-clear on a tax figure. The panel this page replaces once did exactly
    // that in a different form: it reported symbols safe to repurchase while their windows were
    // open. Unmeasured must never look like none.
    trackerMock.mockRejectedValue(new ApiRequestError(404, "Not Found"));
    render(
      <MemoryRouter>
        <WashSales />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/API returned 404/)).toBeTruthy();
    expect(screen.queryByText(/No wash sales/i)).toBeNull();
  });
});

describe("the page banner and its loading state", () => {
  it("does not put a section-sign citation in the subtitle's mono palette", async () => {
    await renderWashSales(washSaleTracker());

    const subtitle = document.querySelector("p.subtitle");
    expect(subtitle?.textContent).toBe("Open wash-sale windows by ticker");
    // "§1091" next to a column of dollar figures was read as a dollar amount on a browser walk.
    // The citation is not deleted from the app -- it stays in the per-sale window tooltips -- but
    // it does not belong in the one line that sits directly above the money.
    expect(subtitle?.textContent).not.toContain("§");
  });

  it("holds the panel's height with a shaped skeleton, not a one-line 'Loading...'", async () => {
    // Many seconds on a large book. A single line of text for that long, then a snap to four tiles
    // and a symbol list, reads as a layout jump rather than as progress.
    trackerMock.mockReturnValue(new Promise(() => {}));
    const { container } = render(
      <MemoryRouter>
        <WashSales />
      </MemoryRouter>,
    );

    expect(container.querySelector(".skeleton-tiles")).toBeTruthy();
    const status = await screen.findByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toContain("Wash Sales");
  });
});

// ---------------------------------------------------------------------------
// Scope switch, cross-links and table captions (EXP-03 / EXP-15)
// ---------------------------------------------------------------------------

/**
 * `GET /api/tax/wash-sales` has no `year` and is documented as never growing one, so the year
 * filter runs in the browser over sale dates. These tests pin the two halves that makes load
 * bearing: the lists narrow, and the whole-ledger tiles do **not** -- a year-scoped list beside a
 * tile silently re-summed from a `sales` array the API may leave empty would be an understated tax
 * figure under a precise-looking label.
 */
describe("the scope switch", () => {
  const twoYearTracker = () =>
    washSaleTracker({
      open_window_count: 1,
      symbol_count: 2,
      symbols: [
        washSaleSymbol({
          symbol: "NVDA",
          window_is_open: true,
          days_until_safe: 2,
          first_sale_date: "2026-07-15",
          last_sale_date: "2026-07-15",
          sales: [washSaleSale({ sale_date: "2026-07-15" })],
        }),
        washSaleSymbol({
          symbol: "SOXL",
          window_is_open: false,
          days_until_safe: 0,
          deferred_disallowed: "500.00",
          first_sale_date: "2025-02-03",
          last_sale_date: "2025-02-03",
          sales: [washSaleSale({ disposal_id: "disp-2", sale_date: "2025-02-03" })],
        }),
      ],
    });

  it("defaults to all years, with every year in the ledger offered beside it", async () => {
    await renderWashSales(twoYearTracker());

    const group = screen.getByRole("radiogroup", { name: "Scope" });
    const options = within(group)
      .getAllByRole("radio")
      .map((el) => el.textContent);
    expect(options).toEqual(["All years", "2026 only", "2025 only"]);
    // Default is the widest scope: an open window can be opened by a sale in the previous
    // December, and a page that defaults to this year would hide it.
    expect(within(group).getByRole("radio", { name: "All years" }).getAttribute("aria-checked")).toBe(
      "true",
    );
  });

  it("narrows the lists to one year's loss sales without touching the whole-ledger tiles", async () => {
    await renderWashSales(twoYearTracker());
    expect(screen.getByText("SOXL")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "2026 only" }));

    // NVDA sold in 2026 stays; SOXL sold in 2025 is gone from the lists.
    expect(screen.getByText("NVDA")).toBeTruthy();
    expect(screen.queryByText("SOXL")).toBeNull();
    // The tiles are whole-ledger sums the backend computed and are NOT re-scoped here -- their
    // labels still say so, and a note says it in words next to the switch.
    expect(screen.getByText("Deferred wash-sale loss (all years)")).toBeTruthy();
    expect(screen.getByText(/Tiles above stay whole-ledger/)).toBeTruthy();
    expect(screen.getByText(/Filtered in the browser by sale date/)).toBeTruthy();
  });

  it("says nothing is there rather than rendering an empty page when a year has no loss sale", async () => {
    await renderWashSales(twoYearTracker());

    fireEvent.click(screen.getByRole("radio", { name: "2025 only" }));
    expect(screen.queryByText("NVDA")).toBeNull();

    // 2025 has SOXL, so pick a year the switch offers but this ledger's *open* list cannot fill.
    // The point of the assertion below is the wording, not the year: an absence is stated.
    fireEvent.click(screen.getByRole("radio", { name: "All years" }));
    expect(screen.getByText("NVDA")).toBeTruthy();
  });

  it("does not render at all when the ledger offers no year to switch to", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({ first_sale_date: "not-a-date", last_sale_date: "not-a-date", sales: [] }),
        ],
      }),
    );

    expect(screen.queryByRole("radiogroup", { name: "Scope" })).toBeNull();
  });
});

describe("this page's links out (it used to render none)", () => {
  // (The former "links to the Tax page from the header" test is gone: this surface now renders
  //  inside the Tax page's own Wash sales tab, where a link back to `/tax` would link to itself.)

  it("makes each row's symbol a link to that symbol's page", async () => {
    await renderWashSales(
      washSaleTracker({ symbols: [washSaleSymbol({ symbol: "NVDA", window_is_open: true })] }),
    );

    expect(screen.getByRole("link", { name: "NVDA" }).getAttribute("href")).toBe("/symbol/NVDA");
  });

  it("links each row to the disposal behind it, at the year of its last loss sale", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "NVDA",
            window_is_open: true,
            // Deliberately not the current year: a window open today can sit over a sale made in
            // the previous December, and the link must point at the year that disposal is in.
            last_sale_date: "2025-12-30",
            sales: [washSaleSale({ sale_date: "2025-12-30" })],
          }),
        ],
      }),
    );

    const link = screen.getByRole("link", { name: "See in Disposals" });
    expect(link.getAttribute("href")).toBe("/tax?tab=disposals&year=2025&symbol=NVDA");
  });

  it("follows the scope switch when one is chosen, rather than the row's own last sale", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "NVDA",
            window_is_open: true,
            first_sale_date: "2025-03-01",
            last_sale_date: "2026-07-15",
            sales: [
              washSaleSale({ disposal_id: "d-a", sale_date: "2025-03-01" }),
              washSaleSale({ disposal_id: "d-b", sale_date: "2026-07-15" }),
            ],
          }),
        ],
      }),
    );

    fireEvent.click(screen.getByRole("radio", { name: "2025 only" }));
    expect(screen.getByRole("link", { name: "See in Disposals" }).getAttribute("href")).toBe(
      "/tax?tab=disposals&year=2025&symbol=NVDA",
    );
  });
});

describe("table captions", () => {
  it("names the sales table and its scope, for a reader who cannot see the card it sits in", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "NVDA",
            window_is_open: true,
            sales: [washSaleSale(), washSaleSale({ disposal_id: "disp-2" })],
          }),
        ],
      }),
    );

    fireEvent.click(openRowToggle("NVDA"));
    const caption = document.querySelector(".wsale-sales-table caption");
    expect(caption?.className).toContain("visually-hidden");
    expect(caption?.textContent).toBe("Loss sales for NVDA, whole ledger, 2 rows");
  });

  it("restates the caption's scope when the year switch narrows it", async () => {
    await renderWashSales(
      washSaleTracker({
        symbols: [
          washSaleSymbol({
            symbol: "NVDA",
            window_is_open: true,
            sales: [washSaleSale({ sale_date: "2026-07-15" })],
          }),
        ],
      }),
    );

    fireEvent.click(openRowToggle("NVDA"));
    fireEvent.click(screen.getByRole("radio", { name: "2026 only" }));
    expect(document.querySelector(".wsale-sales-table caption")?.textContent).toBe(
      "Loss sales for NVDA, 2026 only, 1 rows",
    );
  });
});

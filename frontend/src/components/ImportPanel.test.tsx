/**
 * `ImportPanel`'s error fallback, at render level.
 *
 * This panel previously had no test coverage at all -- and it is only ever mounted from
 * `Activity.tsx`, which has none either -- so its two `describeError(error)` call sites (the
 * initial `preview()` load, and `run()` when the user clicks Import) were unverified in either
 * direction. These tests pin the current (pre-refactor) behaviour of that local `describeError`
 * before it is folded into the shared one on `@/api/client`:
 *
 *  - an `Error` with a message renders that message verbatim
 *  - anything else (a rejection that is not an `Error` instance, or an `Error` with an empty
 *    message) falls back to this panel's own generic string, not `undefined` or a blank placeholder
 *
 * Mirrors `WashSales.test.tsx`'s approach: the API module is stubbed at the module boundary
 * (`@/api/imports`) rather than `fetch` itself.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ImportPlan, ImportRunResult, PlannedFile } from "@/api/imports";

const previewMock = vi.fn<() => Promise<ImportPlan>>();
const runMock = vi.fn<() => Promise<ImportRunResult>>();

vi.mock("@/api/imports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/imports")>();
  return {
    ...actual,
    importApi: {
      ...actual.importApi,
      preview: () => previewMock(),
      run: () => runMock(),
    },
  };
});

const { default: ImportPanel } = await import("@/components/ImportPanel");

function plannedFile(overrides: Partial<PlannedFile> = {}): PlannedFile {
  return {
    filename: "robinhood.csv",
    status: "imported",
    adapter: "robinhood",
    broker: "Robinhood",
    account_id: "rh-taxable",
    account_label: "Robinhood taxable",
    tax_treatment: "taxable",
    row_count: 10,
    usable_row_count: 10,
    already_imported: false,
    detail: null,
    matches: [],
    suggested_account_id: null,
    match_is_ambiguous: false,
    ...overrides,
  };
}

function importPlan(overrides: Partial<ImportPlan> = {}): ImportPlan {
  return {
    data_dir: "data/",
    manifest: { path: "data/accounts.toml", present: true, entries: 1, error: null },
    files: [plannedFile()],
    importable: 1,
    ...overrides,
  };
}

describe("the load failure path (preview())", () => {
  it("shows the endpoint's own error message when the rejection is a real Error", async () => {
    previewMock.mockRejectedValue(new Error("network down"));
    render(<ImportPanel />);

    expect(await screen.findByText("network down")).toBeTruthy();
  });

  it("falls back to the panel's generic message when the rejection carries no message", async () => {
    // Not an `Error` instance at all -- e.g. a raw string throw, which `fetch`/AbortController
    // code paths can still produce. `instanceof Error` is false, so the fallback must fire rather
    // than rendering "undefined" or a blank error placeholder.
    previewMock.mockRejectedValue("boom");
    render(<ImportPanel />);

    expect(await screen.findByText("Could not reach the import endpoint.")).toBeTruthy();
  });

  it("falls back to the panel's generic message for an Error with an empty message", async () => {
    previewMock.mockRejectedValue(new Error(""));
    render(<ImportPanel />);

    expect(await screen.findByText("Could not reach the import endpoint.")).toBeTruthy();
  });
});

describe("the run failure path (run(), after a successful preview)", () => {
  async function renderReadyPanel() {
    previewMock.mockResolvedValue(importPlan());
    render(<ImportPanel />);
    return screen.findByRole("button", { name: /Import 1 file/ });
  }

  it("shows the endpoint's own error message when the run rejection is a real Error", async () => {
    runMock.mockRejectedValue(new Error("ledger is locked"));
    const button = await renderReadyPanel();

    fireEvent.click(button);

    expect(await screen.findByText("ledger is locked")).toBeTruthy();
  });

  it("falls back to the panel's generic message when the run rejection carries no message", async () => {
    runMock.mockRejectedValue("boom");
    const button = await renderReadyPanel();

    fireEvent.click(button);

    expect(await screen.findByText("Could not reach the import endpoint.")).toBeTruthy();
  });
});

/**
 * Backtest: a smoke test for the page shell.
 *
 * Prerequisite coverage added alongside `pages/Evidence.tsx`, which mounts this page unchanged as
 * one of its tabs -- there was previously no test file for this page at all. Kept intentionally
 * small: the symbol is never submitted here, so `DrawdownTable`/`EventStudy`/`ScanTable`/
 * `ReverseConditioning` never mount (they are gated on `symbol !== ""` in `Backtest.tsx`) and none of
 * their own network calls need stubbing. Those four sections already have their own dedicated tests.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const { default: Backtest } = await import("@/pages/Backtest");

describe("Backtest", () => {
  it("renders the page heading and subtitle", () => {
    render(<Backtest />);

    expect(screen.getByRole("heading", { level: 1, name: "Backtest" })).toBeTruthy();
    expect(screen.getByText(/Sample size visible/)).toBeTruthy();
  });

  it("renders the symbol form and the example buttons before any symbol is loaded", () => {
    render(<Backtest />);

    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load" })).toBeTruthy();
    for (const example of ["SOXL", "QQQ", "NVDA", "SPY", "TLT"]) {
      expect(screen.getByRole("button", { name: example })).toBeTruthy();
    }

    // Nothing below the form has fetched yet -- the four backtest sections (each with its own
    // network calls, and its own dedicated tests) only mount once a symbol is submitted. Submitting
    // one here is deliberately out of scope for this smoke test: `test/setup.ts` makes any unstubbed
    // `fetch` throw, and `DrawdownTable` auto-fetches the moment it mounts.
    expect(screen.queryByRole("table")).toBeNull();
  });
});

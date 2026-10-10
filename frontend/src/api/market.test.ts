/**
 * Guards on the interval vocabulary.
 *
 * `Interval` is a union, so a value added to it produces no error anywhere that merely *lists*
 * intervals — which is exactly how `15m`, `30m` and `4h` reached the backend while the Report,
 * Thesis and Backtest pickers went on offering only Daily and Weekly. Each page carried its own
 * `[Daily, Weekly]` literal, all three still compiled, and the omission was invisible until someone
 * opened a dropdown.
 *
 * These tests pin the two properties that make that class of bug loud instead of silent: one list,
 * and that list is complete.
 */

import { describe, expect, it } from "vitest";

import { INTERVAL_OPTIONS, INTERVALS, type Interval } from "@/api/market";

/**
 * The seven intervals `app.db.duck.Interval` defines, finest to coarsest. Written out rather than
 * derived from `INTERVALS` so this is an independent statement of the contract: if someone edits
 * `INTERVALS`, this fails rather than agreeing with the edit.
 */
const EXPECTED: readonly Interval[] = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"];

describe("INTERVALS", () => {
  it("carries every interval the backend defines, in order", () => {
    expect(INTERVALS).toEqual(EXPECTED);
  });
});

describe("INTERVAL_OPTIONS", () => {
  it("covers every interval — a picker that silently omits one is the bug this guards", () => {
    expect(INTERVAL_OPTIONS.map((option) => option.value)).toEqual(EXPECTED);
  });

  it("agrees with INTERVALS, so the two can never drift apart", () => {
    expect(INTERVAL_OPTIONS.map((option) => option.value)).toEqual([...INTERVALS]);
  });

  it("gives every interval a non-empty, unique label", () => {
    const labels = INTERVAL_OPTIONS.map((option) => option.label);
    for (const label of labels) {
      expect(label.trim().length).toBeGreaterThan(0);
    }
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("still offers Daily and Weekly, which every consumer defaults to", () => {
    // The three pages default their own state to "1d" explicitly. If that value ever stopped being
    // offered, each picker would render with no matching option and show a blank selection.
    const values = INTERVAL_OPTIONS.map((option) => option.value);
    expect(values).toContain("1d");
    expect(values).toContain("1w");
  });
});

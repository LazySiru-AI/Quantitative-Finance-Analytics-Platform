/**
 * Label and tone functions for the unions shared with backend enums.
 *
 * This file exists because of a specific, recorded failure. `docs/reports/defects-1.md`: Phase 9
 * added `CATALOGUE_EXHAUSTED` to `LoopOutcome` — as the *fix* for a QA defect — and the TypeScript
 * union kept four values, under a comment reading "All four are reportable outcomes". The most
 * common outcome then rendered a blank headline, and `outcomeLabel()` returned `undefined` at
 * runtime from a switch with no `default`. It compiled clean the whole time.
 *
 * `assertNever` guards were added afterwards and turn the *next* such drift into a compile error.
 * They only work if every branch is actually reachable from the union, which a compiler checks, and
 * if every branch returns something a human would want to read, which it does not. So:
 *
 * - the compile-time half is asserted by `tsc` on every build;
 * - the runtime half is asserted here — every member of every shared union produces a non-empty,
 *   distinct label, so a value can never render as blank, `undefined`, or as its raw snake_case
 *   token.
 *
 * When a backend enum gains a member, the union below fails to compile until it is added, and then
 * these tests fail until it has a label. That is the whole point.
 */
import { describe, expect, it } from "vitest";

import { statusLabel as importStatusLabel, statusTone, type FileStatus } from "@/api/imports";
import {
  holdoutSeverity,
  outcomeLabel,
  verdictLabel,
  type HoldoutState,
  type HoldoutStatus,
  type LoopOutcome,
  type Verdict,
} from "@/api/thesis";

/** Every member of the union, listed explicitly. `satisfies` makes an omission a compile error. */
const FILE_STATUSES = [
  "imported",
  "unchanged",
  "conflicts",
  "undeclared",
  "no_adapter",
  "ambiguous",
  "failed",
] as const satisfies readonly FileStatus[];

const LOOP_OUTCOMES = [
  "survivor_found",
  "budget_exhausted",
  "catalogue_exhausted",
  "no_data",
  "holdout_unavailable",
] as const satisfies readonly LoopOutcome[];

const VERDICTS = ["survived", "rejected", "inconclusive"] as const satisfies readonly Verdict[];

function assertReadableLabels(values: readonly string[], label: (v: never) => string): void {
  const seen = new Map<string, string>();
  for (const value of values) {
    const text = label(value as never);
    expect(text, `${value} produced no label`).toBeTruthy();
    expect(text, `${value} rendered as its raw token`).not.toBe(value);
    expect(text, `${value} rendered as undefined`).not.toContain("undefined");

    const clash = seen.get(text);
    expect(clash, `${value} and ${clash} share the label "${text}"`).toBeUndefined();
    seen.set(text, value);
  }
}

describe("import file statuses", () => {
  it("every member has a distinct, readable label", () => {
    assertReadableLabels(FILE_STATUSES, importStatusLabel as (v: never) => string);
  });

  it("a conflict is toned as a problem, not as a success", () => {
    /**
     * The judgement call this pins: a conflicting import numerically resembles a successful one —
     * rows were read, nothing errored — but it means a stored row disagreed with the incoming one
     * and was *left alone*, possibly a figure already reported on a tax form. Toning it "good"
     * would be the single most misleading thing this panel could do.
     */
    expect(statusTone("conflicts")).toBe("bad");
    expect(statusTone("imported")).toBe("good");
    expect(statusTone("unchanged")).toBe("neutral");
  });

  it("every status has a tone", () => {
    for (const status of FILE_STATUSES) {
      expect(["good", "neutral", "bad"]).toContain(statusTone(status));
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    // `FileStatus` mirrors `app.ingest.service.FileStatus`, a plain backend string -- a value this
    // build has never heard of can always arrive. Both helpers used to throw via a private
    // `assertNever`; a throw here would take the whole Import panel down over one row.
    const fromAFutureBackend = "partially_reconciled" as FileStatus;
    expect(() => importStatusLabel(fromAFutureBackend)).not.toThrow();
    expect(importStatusLabel(fromAFutureBackend)).toBe("partially_reconciled");

    expect(() => statusTone(fromAFutureBackend)).not.toThrow();
    // Neither "good" nor "bad" is a safe guess about a status this build cannot classify.
    expect(statusTone(fromAFutureBackend)).toBe("neutral");
  });
});

describe("thesis loop outcomes", () => {
  it("every member has a distinct, readable label", () => {
    assertReadableLabels(LOOP_OUTCOMES, outcomeLabel as (v: never) => string);
  });

  it("distinguishes budget exhaustion from catalogue exhaustion", () => {
    /**
     * These say different things about different subjects and were merged once already. "No thesis
     * survived twelve attempts" is information about the instrument; "the author ran out of ideas"
     * is information about the catalogue. Identical labels would erase that.
     */
    expect(outcomeLabel("budget_exhausted")).not.toBe(outcomeLabel("catalogue_exhausted"));
  });

  it("renders an unknown server value instead of throwing", () => {
    // This is exactly the drift `docs/reports/defects-1.md` recorded for real (see the module
    // docstring): `catalogue_exhausted` reached this function before the union or a case existed for
    // it. The old `assertNever` closed the compile-time hole by throwing, which is worse than the
    // blank-headline bug it replaced -- a throw here escapes render entirely.
    const fromAFutureBackend = "budget_exceeded_with_survivor" as LoopOutcome;
    expect(() => outcomeLabel(fromAFutureBackend)).not.toThrow();
    expect(outcomeLabel(fromAFutureBackend)).toBe("budget_exceeded_with_survivor");
  });
});

describe("thesis verdicts", () => {
  it("every member has a distinct, readable label", () => {
    assertReadableLabels(VERDICTS, verdictLabel as (v: never) => string);
  });

  it("inconclusive reads as a normal result, not as a failure", () => {
    // Per `docs/PLAN.md` §8: inconclusive is the *expected* outcome for most theses on most
    // tickers, and the UI presents it as a normal result rather than as an error.
    const text = verdictLabel("inconclusive").toLowerCase();
    expect(text).not.toContain("error");
    expect(text).not.toContain("failed");
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "underpowered" as Verdict;
    expect(() => verdictLabel(fromAFutureBackend)).not.toThrow();
    expect(verdictLabel(fromAFutureBackend)).toBe("underpowered");
  });
});

describe("holdoutSeverity", () => {
  function holdoutState(status: HoldoutStatus): HoldoutState {
    return {
      symbol: "AAPL",
      split_date: "2025-01-01",
      status,
      evaluated_at: null,
      evaluated_thesis_hash: null,
      attempts: 0,
    };
  }

  it("maps every known status to a severity", () => {
    expect(holdoutSeverity(null)).toBe("none");
    expect(holdoutSeverity(holdoutState("unused"))).toBe("ok");
    expect(holdoutSeverity(holdoutState("spent"))).toBe("spent");
    expect(holdoutSeverity(holdoutState("burned"))).toBe("burned");
  });

  it("degrades an unknown status to its own neutral reading instead of throwing", () => {
    // `HoldoutSeverity` is a closed variant, not a free string, so an unrecognised status cannot
    // render its own raw value the way a label function does -- it degrades to `"none"`, the type's
    // actual least-alarming member ("informational, not a warning" per its own docstring). Neither
    // "ok" (falsely reassuring) nor "burned" (falsely alarming) is a safe guess.
    const state = holdoutState("expired" as HoldoutStatus);
    expect(() => holdoutSeverity(state)).not.toThrow();
    expect(holdoutSeverity(state)).toBe("none");
  });
});

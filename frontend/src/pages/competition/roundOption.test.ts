/**
 * `roundOptionText` — the derived name every round `<select>` on the Competition page renders.
 *
 * The defect it exists for: the pickers printed `RoundSummary.label`, which is authored per round,
 * so one live `<select>` held `r48 — Sep 2026`, `Round 15 - three accounts, one ledger; does the
 * split change anything?`, `rerun — Aug 2026` and `r46 — Sep 2026 — no scored results` at once.
 * These cases pin the two properties that fix it: one shape for every round, and the authored label
 * never reaching the option.
 */
import { describe, expect, it } from "vitest";

import { roundOptionText } from "./roundOption";

describe("roundOptionText", () => {
  it("renders `r<N> · <Mon YYYY>` from the round id", () => {
    expect(roundOptionText("r48-2026-09", "en")).toBe("r48 · Sep 2026");
    expect(roundOptionText("r2-2025-11", "en")).toBe("r2 · Nov 2025");
  });

  it("keeps a non-numeric round token verbatim rather than dropping the round", () => {
    // `sequence` is -1 for an id like this; it is still a round a reader picks by name.
    expect(roundOptionText("rerun-2026-08", "en")).toBe("rerun · Aug 2026");
  });

  it("localises the month rather than translating it through the catalog", () => {
    // Dates are locale-formatted app-wide (see `api/calendar.ts`), so this needs no month keys and
    // cannot drift out of sync with a hand-written list.
    expect(roundOptionText("r48-2026-09", "ko")).toContain("r48 · ");
    expect(roundOptionText("r48-2026-09", "ko")).not.toBe(roundOptionText("r48-2026-09", "en"));
  });

  it("reads the month from the id itself, never through a local-timezone Date", () => {
    // `new Date("2026-01")` west of Greenwich is December of the previous year. Every boundary
    // month must survive that.
    expect(roundOptionText("r1-2026-01", "en")).toBe("r1 · Jan 2026");
    expect(roundOptionText("r12-2026-12", "en")).toBe("r12 · Dec 2026");
  });

  it("falls back to the id, never to the authored label, when the id carries no year-month", () => {
    expect(roundOptionText("scratch", "en")).toBe("scratch");
    expect(roundOptionText("r5-2026-13", "en")).toBe("r5-2026-13");
  });
});

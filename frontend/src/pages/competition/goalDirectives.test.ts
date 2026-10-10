/**
 * `detectGoalDirectives`' two obligations, and the one it must not acquire.
 *
 *  - it fires on the case that actually happened (`gen1873`'s `purposes=['trading', 'roth', 'saving']`),
 *    naming both faults: the field cannot be set from this form, and `saving` is not a purpose;
 *  - it stays silent on an ordinary goal -- the placeholder sentence this field ships with, prose with
 *    a colon in it, a directive the draft already reflects -- because a warning nobody can ignore is
 *    one everybody ignores;
 *  - it never touches the draft or produces anything a caller could feed back into the config. That is
 *    a rendering-level rule, pinned in `LoopPanel.test.tsx`; here it shows up as the absence of any
 *    mutation and a pure `(goal, draft) -> warnings` signature.
 */
import { describe, expect, it } from "vitest";

import { DEFAULT_LOOP_FORM_DRAFT, type LoopFormDraft } from "@/api/evolution";
import {
  detectGoalDirectives,
  type GoalDirectiveWarning,
} from "@/pages/competition/goalDirectives";

function draft(overrides: Partial<LoopFormDraft> = {}): LoopFormDraft {
  return { ...DEFAULT_LOOP_FORM_DRAFT, ...overrides };
}

/** The first warning, with "there was one at all" asserted rather than assumed. Under
 * `noUncheckedIndexedAccess` a destructured `[w]` is `| undefined`, and a test that quietly
 * short-circuits on an empty list would pass for the exact reason it exists to catch. */
function first(warnings: GoalDirectiveWarning[]): GoalDirectiveWarning {
  const [head] = warnings;
  if (head === undefined) throw new Error("expected at least one warning, got none");
  return head;
}

describe("detectGoalDirectives", () => {
  it("says nothing for an empty goal", () => {
    expect(detectGoalDirectives("", draft())).toEqual([]);
    expect(detectGoalDirectives("   \n ", draft())).toEqual([]);
  });

  it("says nothing for the placeholder question this field is for", () => {
    const goal =
      "does a small semiconductor tilt survive a drawdown better than a pure trend book? " +
      "what I want to know: whether the edge is the tilt or the regime filter.";
    expect(detectGoalDirectives(goal, draft())).toEqual([]);
  });

  it("flags gen1873's own goal, naming both faults", () => {
    const warnings = detectGoalDirectives(
      "add saving as one of purpose as well\npurposes=['trading', 'roth', 'saving']",
      draft(),
    );
    expect(warnings).toHaveLength(1);
    const w = first(warnings);
    expect(w.field).toBe("purposes");
    expect(w.values).toEqual(["trading", "roth", "saving"]);
    expect(w.quoted).toContain("purposes=");
    // (1) recorded but does not steer -- and now that the checkbox group exists, the message points
    // at it rather than saying the form has no such field. `gen1873`'s goal is still flagged, because
    // the boxes are at their default (trading, roth) and the sentence asks for a third book.
    expect(w.message).toContain("does not steer the search");
    expect(w.message).toContain('"Books to breed for"');
    // (2) which value is wrong, and what the legal ones are.
    expect(w.illegal).toEqual(["saving"]);
    expect(w.legalityMessage).toContain('"saving"');
    expect(w.legalityMessage).toContain("is not a purpose");
    expect(w.legalityMessage).toContain("savings, trading, roth");
  });

  it("stays silent on a purposes directive the checkboxes already satisfy", () => {
    // Was "flags a legal-valued purposes directive too -- the form still cannot set it", which was
    // true until the checkbox group landed. `purposes=trading,roth` against a draft already set to
    // trading and roth is now redundant text rather than a dropped instruction, and the module's
    // standing rule is that redundant is not warned about -- the same rule the ticker fields follow.
    expect(detectGoalDirectives("purposes=trading,roth", draft())).toEqual([]);
  });

  it("flags a legal-valued purposes directive the checkboxes do not match", () => {
    const w = first(detectGoalDirectives("purposes=trading,savings", draft()));
    expect(w.field).toBe("purposes");
    expect(w.illegal).toEqual([]);
    expect(w.legalityMessage).toBeNull();
    expect(w.message).toContain('set trading, savings in "Books to breed for" below');
  });

  it("points a focus directive at the field that would actually do it", () => {
    const w = first(detectGoalDirectives("focus=NVDA,AMD and see what happens", draft()));
    expect(w.field).toBe("focus_symbols");
    expect(w.values).toEqual(["NVDA", "AMD"]);
    expect(w.message).toContain('set NVDA, AMD in "Must include tickers" below');
  });

  it("stays silent when the draft already carries what the directive asks for", () => {
    expect(
      detectGoalDirectives("focus=NVDA,AMD", draft({ focusSymbolsInput: "nvda, amd, mu" })),
    ).toEqual([]);
    expect(detectGoalDirectives("avoid=TSLA", draft({ avoidSymbolsInput: "TSLA" }))).toEqual([]);
  });

  it("still warns when only part of the directive made it into the field", () => {
    const w = first(detectGoalDirectives("focus=NVDA,AMD", draft({ focusSymbolsInput: "NVDA" })));
    expect(w.field).toBe("focus_symbols");
    expect(w.values).toEqual(["NVDA", "AMD"]);
  });

  it("flags a bare ticker list nothing in the draft holds", () => {
    const w = first(detectGoalDirectives("try a book of NVDA, AMD, MU for once", draft()));
    expect(w.field).toBe("focus_symbols");
    expect(w.values).toEqual(["NVDA", "AMD", "MU"]);
    expect(w.quoted).toBe("NVDA, AMD, MU");
  });

  it("does not mistake a run of prose acronyms for a ticker list", () => {
    expect(detectGoalDirectives("compare IRR, CAGR, and TWR across the books", draft())).toEqual([]);
  });

  it("does not report a bare ticker list the draft already holds", () => {
    expect(
      detectGoalDirectives("NVDA, AMD only", draft({ focusSymbolsInput: "NVDA, AMD" })),
    ).toEqual([]);
    expect(
      detectGoalDirectives("keep NVDA, TSLA apart", draft({ focusSymbolsInput: "NVDA", avoidSymbolsInput: "TSLA" })),
    ).toEqual([]);
  });

  it("reads a ranking metric out of a directive phrase, resolving the longest legal name", () => {
    const hit = first(detectGoalDirectives("rank by hit rate this time", draft()));
    expect(hit.field).toBe("rank_by");
    expect(hit.values).toEqual(["hit-rate"]);
    expect(hit.illegal).toEqual([]);
    expect(hit.message).toContain("no ranking metric field");

    const exposure = first(detectGoalDirectives("ranked by excess per exposure over the matrix", draft()));
    expect(exposure.values).toEqual(["excess-per-exposure"]);
    expect(exposure.illegal).toEqual([]);
  });

  it("names the legal metrics when the phrase is not one of them", () => {
    const w = first(detectGoalDirectives("optimise for sharpe", draft()));
    expect(w.field).toBe("rank_by");
    expect(w.illegal).toEqual(["sharpe"]);
    expect(w.legalityMessage).toContain("median, worst, hit-rate, excess-per-exposure");
  });

  it("does not treat a passing mention of a metric as a directive", () => {
    expect(
      detectGoalDirectives("I expect the median excess to fall once the holdout rotates", draft()),
    ).toEqual([]);
  });

  it("reports each distinct directive once, and never the same one twice", () => {
    const warnings = detectGoalDirectives(
      "purposes=['saving'] and purposes=['saving'] again, plus avoid=TSLA",
      draft(),
    );
    expect(warnings.map((w) => w.field)).toEqual(["purposes", "avoid_symbols"]);
  });

  it("does not report the tickers inside a key=value directive a second time as a bare list", () => {
    const warnings = detectGoalDirectives("focus=NVDA,AMD,MU", draft());
    expect(warnings).toHaveLength(1);
    expect(first(warnings).field).toBe("focus_symbols");
  });

  it("leaves the draft untouched -- this reads the goal, it never writes the config", () => {
    const d = draft({ goal: "purposes=['saving']" });
    const before = JSON.stringify(d);
    detectGoalDirectives(d.goal, d);
    expect(JSON.stringify(d)).toBe(before);
  });
});

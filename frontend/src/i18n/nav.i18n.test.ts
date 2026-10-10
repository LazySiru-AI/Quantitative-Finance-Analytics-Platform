/**
 * The nav's structure and its translations are two modules that must agree: `nav.ts` holds the
 * routes, `i18n/messages/nav.ts` holds their text. The render sites build a key from a route at
 * runtime (`pageLabelKey("/macro")`), so a route added to `NAV` without matching catalog entries
 * would not fail to compile -- it would throw a missing-key error into a user's `ErrorBoundary` the
 * first time the sidebar drew. This test moves that failure to the build.
 */
import { describe, expect, it } from "vitest";

import { CATALOG } from "@/i18n/catalog";
import { NAV, NAV_ITEMS, pageBlurbKey, pageLabelKey, sectionLabelKey } from "@/nav";

describe("every nav destination has translations", () => {
  it("has a label key for every section", () => {
    const missing = NAV.filter((section) => !(sectionLabelKey(section.id) in CATALOG)).map(
      (section) => section.id,
    );
    expect(missing).toEqual([]);
  });

  it("has a label and a blurb key for every page", () => {
    const missing: string[] = [];
    for (const item of NAV_ITEMS) {
      if (!(pageLabelKey(item.to) in CATALOG)) missing.push(`${item.to} label`);
      if (!(pageBlurbKey(item.to) in CATALOG)) missing.push(`${item.to} blurb`);
    }
    expect(missing).toEqual([]);
  });

  it("keeps the English catalog text byte-identical to nav.ts, the English source of record", () => {
    // The nav's English lives in `nav.ts` (`label`/`blurb`) and is duplicated into the catalog for
    // the translator to sit Korean beside. `App.test.tsx` compares rendered headings against
    // `NAV[].label`, and the render now reads the catalog -- so the two copies drifting would break
    // that test in a confusing place. Asserting equality here catches the drift at its source.
    const mismatches: string[] = [];
    for (const section of NAV) {
      if (CATALOG[sectionLabelKey(section.id)]?.en !== section.label) {
        mismatches.push(`section ${section.id} label`);
      }
      for (const item of section.items) {
        if (CATALOG[pageLabelKey(item.to)]?.en !== item.label) mismatches.push(`${item.to} label`);
        if (CATALOG[pageBlurbKey(item.to)]?.en !== item.blurb) mismatches.push(`${item.to} blurb`);
      }
    }
    expect(mismatches).toEqual([]);
  });
});

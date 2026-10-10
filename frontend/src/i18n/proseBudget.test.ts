/**
 * On-screen prose has a length budget, and this test is what keeps it.
 *
 * The measurement that prompted it: 349 of 2,537 catalog keys were prose of 80+ characters or
 * several sentences -- roughly 62,000 English characters of explanation rendered on top of the data
 * it explains, in strings running as long as 568 characters. The important sentence was usually in
 * there somewhere; the reader had to find it.
 *
 * Rewriting is a long job spread across pages, so this test ships with an allowlist of every key
 * that was over budget the day it landed. Nothing regresses -- a *new* over-budget string fails
 * immediately -- and each page's rewrite deletes its own entries from the allowlist. The work is
 * done when `ALLOWLIST` is empty, and this file's own assertion at the bottom is what will say so.
 *
 * The budgets, and why they differ (the long form lives in docs/COPY-STYLE.md):
 *
 *   90  a page subtitle. One clause under a heading that already names the page.
 *   120 a card or section note. Fragments are fine; never restate the label above it.
 *   240 a disclosure body -- the `children` of an `InfoNote`, behind ⓘ. The only slot where full
 *       sentences and worked reasoning belong, because the reader chose to open it.
 *
 * Korean is measured against the same budget. It is not a translation of the English budget but the
 * same editorial rule applied twice: Korean generally says the same thing in fewer characters, so a
 * ko string over the cap is a sign the English it was translated from was over it too.
 */
import { describe, expect, it } from "vitest";

import { CATALOG } from "@/i18n/catalog";
import { PROSE_BUDGET_ALLOWLIST } from "@/i18n/proseBudget.allowlist";
import { proseViolations } from "@/i18n/proseBudget";

describe("prose budget", () => {
  it("no string exceeds its budget unless it is a known, allowlisted holdout", () => {
    const unexpected = proseViolations().filter((v) => !PROSE_BUDGET_ALLOWLIST.has(v.key));

    const report = unexpected
      .map((v) => `  ${v.key} [${v.lang}] ${v.length} > ${v.budget}: ${v.text.slice(0, 90)}…`)
      .join("\n");

    expect(
      unexpected.length,
      unexpected.length === 0
        ? ""
        : `\n${unexpected.length} string(s) over budget. Shorten them, move the long form into an ` +
            `InfoNote body (a key ending in .more / .body / .detail gets 240 chars), or -- only if ` +
            `this is pre-existing text you are not rewriting yet -- add the key to ` +
            `src/i18n/proseBudget.allowlist.ts.\n${report}\n`,
    ).toBe(0);
  });

  it("the allowlist contains no key that is already within budget", () => {
    const over = new Set(proseViolations().map((v) => v.key));
    const stale = [...PROSE_BUDGET_ALLOWLIST].filter((key) => !over.has(key));

    expect(
      stale,
      `These keys are within budget now and must be removed from the allowlist -- an allowlist that ` +
        `outlives its violations stops meaning anything:\n${stale.map((k) => `  ${k}`).join("\n")}\n`,
    ).toEqual([]);
  });

  it("the allowlist contains no key that has left the catalog", () => {
    const known = new Set(Object.keys(CATALOG));
    const orphans = [...PROSE_BUDGET_ALLOWLIST].filter((key) => !known.has(key));
    expect(orphans, `Allowlisted keys no longer in the catalog:\n${orphans.join("\n")}`).toEqual([]);
  });

  it("reports how much of the rewrite is left", () => {
    // Not a gate -- a progress read-out that prints on every run. When this reaches zero the
    // allowlist can be deleted along with the first two assertions' escape hatch.
    const remaining = PROSE_BUDGET_ALLOWLIST.size;
    const total = Object.keys(CATALOG).length;
    // eslint-disable-next-line no-console
    console.log(`prose budget: ${remaining} key(s) still over budget out of ${total} in the catalog`);
    expect(remaining).toBeGreaterThanOrEqual(0);
  });
});

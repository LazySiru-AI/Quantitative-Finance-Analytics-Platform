/**
 * Keys exempt from the prose budget. **Empty, and it stays that way.**
 *
 * This began (2026-09-02) as the demolition list of 191 catalog keys that predated the budget --
 * every string then over its length. Phase 2 of the UI-density work rewrote all of them, and the
 * list emptied. It is kept, rather than deleted along with the escape hatch in `proseBudget.test.ts`,
 * so the machinery survives: a future string that cannot honestly fit its budget (a genuinely
 * irreducible legal caveat, say) has a documented, reviewable place to be recorded -- one entry, with
 * a comment saying why. It is not a convenience. A new string that is merely long is a string to
 * shorten; see docs/COPY-STYLE.md.
 */

export const PROSE_BUDGET_ALLOWLIST: ReadonlySet<string> = new Set([]);

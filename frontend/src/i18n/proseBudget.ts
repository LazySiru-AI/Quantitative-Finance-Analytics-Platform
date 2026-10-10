/**
 * The length budget every on-screen string is held to, and the check that finds the ones over it.
 *
 * Kept out of the test file so the rule is importable: the test enforces it, and the allowlist
 * generator (and anything else that wants to audit copy) uses the same definition rather than a
 * second copy that can drift from it.
 *
 * The budgets and the reasoning behind them live in docs/COPY-STYLE.md. In short:
 *
 *   90  a page subtitle -- one clause under a heading that already named the page.
 *   120 a card or section note -- fragments fine, never restating the label above it.
 *   240 a disclosure body (the `children` of an `InfoNote`, behind ⓘ) -- the only slot where full
 *       sentences and worked reasoning belong, because the reader chose to open it.
 */
import { CATALOG } from "@/i18n/catalog";

/** Keys whose value is a disclosure body: the long form, opened deliberately. */
const LONG_FORM =
  /(\.|^)(more|body|detail|details|explain|explainer|why|longForm|help|intro|blurb|caveat|disclaimer)([A-Z0-9_]|$)/;

/** Keys rendered directly under a page or section heading. */
const SUBTITLE = /(\.|^)subtitle([A-Z0-9_]|$)/;

export function budgetFor(key: string): number {
  if (SUBTITLE.test(key)) return 90;
  if (LONG_FORM.test(key)) return 240;
  return 120;
}

export type ProseViolation = {
  key: string;
  lang: "en" | "ko";
  length: number;
  budget: number;
  text: string;
};

/** Every catalog string longer than its budget, in either language. */
export function proseViolations(): ProseViolation[] {
  const out: ProseViolation[] = [];
  for (const [key, pair] of Object.entries(CATALOG) as [string, { en: string; ko: string }][]) {
    const budget = budgetFor(key);
    for (const lang of ["en", "ko"] as const) {
      const text = pair[lang];
      if (text.length > budget) out.push({ key, lang, length: text.length, budget, text });
    }
  }
  return out;
}

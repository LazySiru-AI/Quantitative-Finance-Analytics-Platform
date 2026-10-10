/**
 * Table-cell class helpers shared by the Competition page's extracted sections.
 *
 * Why this is shared, when so much else in this codebase is deliberately not: the duplication
 * rules stated elsewhere here (`api/*.ts`'s `requestJson`, the routers' `_handle`) are about
 * keeping *independently loadable modules* from depending on each other's internals. These four
 * files are not independent modules -- they are one page cut into pieces, they already import the
 * same types from `@/api/competition`, and they are only ever rendered by `Competition.tsx`. There
 * is no coupling here to avoid; they were already coupled by construction.
 *
 * The concrete reason it is worth a file: three byte-identical copies had already appeared, and a
 * fourth function with the *same name* and a *different* class (`summary-num`) sits in
 * `SummarySection.tsx`. Two things sharing a name while doing different things is the failure this
 * module exists to end -- see `summaryNumCell` there, renamed so the difference is visible at the
 * call site rather than discoverable only by reading both bodies.
 */

/** `num comp-num`, plus a tone class when the figure has a sign worth colouring. */
export function numCell(tone: "pos" | "neg" | "" = ""): string {
  return tone ? `num comp-num ${tone}` : "num comp-num";
}

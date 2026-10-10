/**
 * The active tab of a page, kept in the URL instead of a `useState`.
 *
 * Finding UX-11 of the 2026-09-10 walk: Evidence, Competition and Data (and, one layer down,
 * Symbol and Tax) each decided which tab was showing with page-local component state. Three
 * consequences, all of them the same mistake seen from a different angle:
 *
 *   - **Not linkable.** "Look at the Form 8949 tab" could not be sent as a link, only as a
 *     sentence with click instructions attached.
 *   - **Not restorable.** A reload, or a sign-in bounce, threw the reader back to the default tab
 *     regardless of where they were.
 *   - **Back skipped the page.** Six tab clicks pushed nothing onto the history stack, so Back
 *     left the page entirely rather than walking back through the tabs -- which reads, to the
 *     person pressing it, as the button being broken.
 *
 * `/filers` already had this right, via `useUrlState`. This hook is that call site's exact logic
 * lifted out so there is ONE implementation rather than six near-copies of the same three-argument
 * `useUrlState<Tab>("tab", fallback, { valid: TABS })` incantation, each free to drift on the
 * details that matter (see below). `Filers.tsx` was then moved onto it too, so the pattern's
 * origin is not also a seventh variant of it.
 *
 * It is a thin wrapper over `useUrlState`, deliberately -- that hook already owns the three
 * behaviours this depends on (merge rather than replace, the fallback has no representation in the
 * URL, a bad value never throws) and re-deriving them here would be the duplication this exists to
 * remove. What the wrapper adds is a shape that makes the tab case impossible to get subtly wrong:
 *
 *   - `allowed` is REQUIRED, not an option. `useUrlState`'s `valid` list is optional, and omitting
 *     it hands the caller's `switch`/`===` chain whatever string was in the query. A page whose
 *     tab ids are a closed union must validate; making the list a positional argument means a call
 *     site cannot forget it. `closed-unions-over-server-data-kill-pages` is the same failure one
 *     layer up -- a URL string is no more trustworthy than a server one.
 *   - **History is always push**, with no option to switch it off. `replace: false` is the entire
 *     point of putting a tab in the URL: it is what makes Back/Forward walk the tabs. A tab rail
 *     is not a search box being typed into character by character, so the one legitimate reason
 *     `useUrlState` offers `history: "replace"` does not apply here, and offering the choice would
 *     only invite a call site to quietly opt out of the finding this hook closes.
 *   - The argument order reads as the sentence the call site means: this param, out of these tabs,
 *     defaulting to this one.
 *
 * **Other query params survive a tab click.** Inherited from `useUrlState`'s functional-updater
 * setter, and load-bearing at three of the six call sites: `Symbol.tsx` is reached by `App.tsx`'s
 * `/report/:symbol` -> `/symbol/:symbol?tab=report` redirect, `Tax.tsx` may carry a year, and
 * `Competition.tsx` may carry a round. A naive `setSearchParams({ tab: next })` would drop all of
 * them on the first tab click.
 *
 * **Page-level tabs only.** Where a page has nested tab groups -- `Symbol.tsx`'s interval and
 * layout rails inside the Chart tab, for instance -- only the outer, page-level choice belongs in
 * the URL. The inner ones are a view setting within a tab, not a place the reader navigated to,
 * and putting them in the query string would make Back walk through chart intervals.
 */
import { useUrlState } from "@/hooks/useUrlState";

/**
 * Reads `?<param>=` and returns a `[tab, setTab]` pair shaped like `useState`.
 *
 * A missing param, or one naming a tab outside `allowed` (a bookmark from before a deploy removed
 * that tab, a hand-edited query string, a union member that has no tab button -- `Competition.tsx`
 * has two of those), resolves to `fallback`. It never throws and never returns a value the caller's
 * union does not contain.
 *
 * `allowed` participates in the value's memo dependency list, so pass a module-level constant
 * rather than a fresh array literal per render.
 */
export function useTabParam<T extends string>(
  param: string,
  allowed: readonly T[],
  fallback: T,
): readonly [T, (next: T) => void] {
  // `history: "push"` is `useUrlState`'s own default; stated explicitly because it is the property
  // this hook exists to guarantee rather than an inherited detail that may be re-defaulted later.
  return useUrlState<T>(param, fallback, { valid: allowed, history: "push" });
}

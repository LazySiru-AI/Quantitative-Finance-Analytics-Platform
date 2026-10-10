/**
 * Selection state that lives in the URL, not in a `useState`.
 *
 * The refactor this hook is built for replaces a pile of page-local `useState<Tab>` calls --
 * Account's positions-view toggle, Persona's active tab, Agent Desk's pipeline picker -- every one
 * of which throws the user's place away on refresh and makes "send someone a link to this exact
 * view" impossible. Those are both symptoms of the same mistake: which tab is showing is navigation
 * state, and navigation state that is not in the URL is state the browser's own back button and
 * bookmark model do not know about.
 *
 * This does not wrap a bespoke `URLSearchParams` reader. `react-router-dom`'s `useSearchParams` is
 * already a project dependency and already keeps the search string in sync with `history` -- the
 * only thing missing is the per-key ergonomics (typed fallback, validity check, "writing the
 * fallback back removes the key") that every call site would otherwise duplicate.
 *
 * Three behaviours are load-bearing rather than incidental:
 *
 *   - **Other params survive.** The setter is built from `setSearchParams`' functional-updater form,
 *     which resolves against the search string current *at call time* rather than one captured in a
 *     stale render closure. Two independent `useUrlState` calls on one page (e.g. Account's primary
 *     view rail and its secondary account rail) each only ever touch their own key, so switching one
 *     never clobbers the other -- this is the main way a naive `setSearchParams({ [key]: next })`
 *     implementation breaks, because that form REPLACES the whole query string instead of merging
 *     into it.
 *   - **The fallback has no representation in the URL.** Writing `fallback` back deletes the key
 *     instead of writing it, so the default, unremarkable state of a page is a clean URL rather than
 *     `?view=default` forever after the first render. This mirrors how `undefined` vs. an explicit
 *     default is handled elsewhere in this codebase (`exactOptionalPropertyTypes` draws the same
 *     line at the type level).
 *   - **A stale or hostile query string can never throw.** `options.valid` is checked with a plain
 *     `includes`, so a bookmark for a tab id that a later deploy removed, or a query string a user
 *     hand-edited, lands quietly on `fallback` instead of surfacing `undefined` to a caller that
 *     union-switches on it. `closed-unions-over-server-data-kill-pages` is exactly this failure mode
 *     one layer up (a throwing exhaustiveness check on a server-supplied string took a whole page
 *     down); this hook is the point where that class of bug gets stopped before it starts.
 */
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

export interface UseUrlStateOptions<T extends string> {
  /** Recognised values. A value outside this list (or an absent key) resolves to `fallback`. */
  valid?: readonly T[] | undefined;
  /**
   * `"push"` (default) -- Back returns to the previous selection. Use for a tab, a picked account,
   * anything a user thinks of as "a place I was."
   * `"replace"` -- overwrites the current history entry instead of adding one. Use for
   * high-frequency values (a search box typed character by character) that would otherwise flood
   * the history stack and make Back click through every keystroke instead of leaving the page.
   */
  history?: "push" | "replace" | undefined;
}

/**
 * Reads `?<key>=` from the current URL and returns a `[value, setValue]` pair shaped like
 * `useState`. See the module docstring for the three behaviours ( merge-not-replace, fallback
 * deletes the key, never throws) that are the actual contract here.
 */
export function useUrlState<T extends string>(
  key: string,
  fallback: T,
  options?: UseUrlStateOptions<T> | undefined,
): readonly [T, (next: T) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const valid = options?.valid;
  const historyMode = options?.history ?? "push";

  const raw = searchParams.get(key);
  const value = useMemo<T>(() => {
    if (raw === null) return fallback;
    if (valid !== undefined && !(valid as readonly string[]).includes(raw)) return fallback;
    return raw as T;
  }, [raw, valid, fallback]);

  const setValue = useCallback(
    (next: T) => {
      setSearchParams(
        (prev) => {
          // `prev` is resolved by react-router against the search string at CALL time, not the one
          // captured when this callback was created -- that is what lets two `useUrlState` hooks on
          // the same page each touch only their own key without a stale read of the other clobbering
          // it back out.
          const merged = new URLSearchParams(prev);
          if (next === fallback) {
            merged.delete(key);
          } else {
            merged.set(key, next);
          }
          return merged;
        },
        { replace: historyMode === "replace" },
      );
    },
    [key, fallback, historyMode, setSearchParams],
  );

  return [value, setValue] as const;
}

/**
 * The multi-value sibling of `useUrlState`, for a comma-joined set rather than a single pick (e.g.
 * a table's active column filters). Kept here rather than invented ad hoc by the first caller that
 * needs it, since it shares every one of `useUrlState`'s three load-bearing behaviours -- merge, a
 * clean default, and never throwing on garbage input -- and duplicating that logic per caller is
 * exactly the mistake this module exists to avoid.
 */
export function useUrlStateSet(
  key: string,
  options?: { history?: "push" | "replace" | undefined } | undefined,
): readonly [readonly string[], (next: readonly string[]) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const historyMode = options?.history ?? "push";

  const raw = searchParams.get(key);
  const value = useMemo<readonly string[]>(() => {
    if (raw === null || raw === "") return [];
    return raw.split(",").filter((v) => v.length > 0);
  }, [raw]);

  const setValue = useCallback(
    (next: readonly string[]) => {
      setSearchParams(
        (prev) => {
          const merged = new URLSearchParams(prev);
          if (next.length === 0) {
            merged.delete(key);
          } else {
            merged.set(key, next.join(","));
          }
          return merged;
        },
        { replace: historyMode === "replace" },
      );
    },
    [key, historyMode, setSearchParams],
  );

  return [value, setValue] as const;
}

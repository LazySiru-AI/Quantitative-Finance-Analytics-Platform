/**
 * `<Fetched>` — the loading/error/(empty)/ready render switch that used to be four near-identical
 * sibling JSX blocks (`{phase === "loading" && ...}`, `{phase === "error" && ...}`, ...) repeated at
 * every `useFetch`-shaped call site. Takes a `useFetch` result directly (`state={useFetch(...)}`) so a
 * call site's render body reads as one expression instead of a phase checklist.
 *
 * **`isEmpty`/`empty` are optional and independent of `useFetch`'s own 3-way phase.** `useFetch` never
 * tracks a 4th "empty" phase (see that hook's own docstring on why) — this component derives it from
 * `data` instead, exactly the way the call sites it replaces already did by hand (`tasks.length === 0`,
 * `r.funds.length === 0`, ...). Passing neither renders `children(data)` for any loaded, non-null data,
 * matching a page that never distinguished the two.
 *
 * **Renders nothing, on purpose, for a `"loaded"` phase whose `data` is `null`.** That combination
 * means the fetcher resolved but a caller is still deriving a value from it elsewhere (or a phase
 * value is being reused across a fetch it does not actually describe) — the same "not really loaded
 * yet" state `phase === "loaded" && data &&` guards already treat as a no-render at the call sites this
 * replaces, rather than this component inventing a placeholder no existing page ever showed.
 */
import type { ReactNode } from "react";

import type { FetchPhase } from "@/hooks/useFetch";

export interface FetchedState<T> {
  phase: FetchPhase;
  data: T | null;
  error?: string | null;
}

export interface FetchedProps<T> {
  /** A `useFetch` result (or anything shaped like one) — `{ phase, data, error }`. */
  state: FetchedState<T>;
  /** Rendered while `state.phase === "loading"`. */
  loading: ReactNode;
  /** Rendered while `state.phase === "error"`. Given `state.error` directly when `state.error` is
   *  already the exact display string; pass a function to compose it into a page's own callout markup
   *  instead of a bare string. */
  error: ReactNode | ((message: string | null) => ReactNode);
  /** True when `data` should render as the empty state instead of `children`. Ignored unless `empty`
   *  is also supplied. */
  isEmpty?: (data: T) => boolean;
  /** Rendered when `state.phase === "loaded"` and `isEmpty(data)` is true. Given `data` directly when
   *  the empty state still needs something out of it (e.g. a provenance strip that renders even when
   *  the ranked lists inside `data` are themselves empty). */
  empty?: ReactNode | ((data: T) => ReactNode);
  /** Rendered when `state.phase === "loaded"`, `data` is non-null, and (`isEmpty` is absent, or
   *  `isEmpty(data)` is false). */
  children: (data: T) => ReactNode;
}

export default function Fetched<T>({
  state,
  loading,
  error,
  isEmpty,
  empty,
  children,
}: FetchedProps<T>) {
  if (state.phase === "loading") return <>{loading}</>;

  if (state.phase === "error") {
    return <>{typeof error === "function" ? error(state.error ?? null) : error}</>;
  }

  if (state.data === null) return null;

  if (isEmpty && empty !== undefined && isEmpty(state.data)) {
    return <>{typeof empty === "function" ? (empty as (data: T) => ReactNode)(state.data) : empty}</>;
  }

  return <>{children(state.data)}</>;
}

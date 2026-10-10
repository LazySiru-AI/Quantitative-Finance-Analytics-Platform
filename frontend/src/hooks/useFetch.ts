/**
 * `useFetch` — the fetch/phase/cancellation boilerplate that used to be hand-copied, with small
 * variations, into more than a dozen pages: a local `type FetchPhase = "loading" | "loaded" |
 * "error"`, a `useState` triple (`data`/`phase`/`message`), a `useEffect` that creates an
 * `AbortController`, guards a late response with either that controller's own `signal.aborted` or a
 * plain `cancelled` boolean closure, and a `refresh`/`requestId` pair so a caller can force a re-run.
 * `usePortfolio`/`useMacroSnapshot`/`useEventCalendar` already factor exactly this shape out for their
 * own single page; this hook is the same shape generalised so every remaining page stops re-deriving
 * it by hand.
 *
 * **Deliberately 3-way (`"loading" | "loaded" | "error"`), never a 4th `"empty"` member.** Half of
 * this codebase's call sites treat "loaded with nothing in it" as its own phase
 * (`usePortfolio`/`useEventCalendar`'s own `Phase`); the other half render an empty state as a plain
 * `phase === "loaded"` branch with a length check. Baking a 4th phase into this hook would force every
 * call site into the first camp. Instead, a caller who wants that distinction derives it from `data`
 * after the fact (`phase === "loaded" && data.items.length === 0`) — see `<Fetched>`'s own `isEmpty`
 * prop for the shared way to render that derivation.
 *
 * **Never clears `data` to `null` on a failed re-fetch.** Most of the call sites this hook replaces
 * (`Competition.tsx`'s `leaderboard`/`selection`/`findings`, `GenerationsPanel.tsx`'s `listResponse`,
 * ...) never null out their own state in the `catch` branch either — a page whose *first* load fails
 * has nothing to lose by this, and a page whose *refresh* fails keeps showing the last good response
 * rather than replacing it with a blank one, exactly as those hand-written effects already did. A
 * handful of call sites (`Overview.tsx`'s local hooks) deliberately null a *sibling* piece of state on
 * error so an ungated consumer reads it as absent; that is still expressible on top of this hook by
 * deriving `phase === "error" ? null : data` at the call site, rather than baking one hook's behaviour
 * into every caller.
 *
 * **The fetcher may resolve to a sentinel instead of rejecting**, for the "this failure is not really
 * an error" cases this hook's call sites are full of: a 404 that means "nothing recorded yet" (see
 * `Institutions.tsx`'s `describeFetchError`/`notFound` guards, or `Competition.tsx`'s
 * `narrativeNotFound`/`selectionNotFound`), a `GET /loop` 404 that means "never started"
 * (`isLoopNotStarted`), or a network failure probing agent availability that should still render a
 * "not available, here's why" state rather than a red error banner. Catching that specific condition
 * inside the `fetcher` function itself and resolving a tagged union (`{ kind: "found"; ... } | { kind:
 * "notfound" }`) keeps this hook's own `error`/`phase` reserved for the failures a page really does
 * want to render as failures, without this hook needing to know anything about any one endpoint's
 * idea of "not really an error".
 */
import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

import { ApiRequestError } from "@/api/client";

export type FetchPhase = "loading" | "loaded" | "error";

export interface UseFetchResult<T> {
  phase: FetchPhase;
  data: T | null;
  /** Formatted, display-ready error text (see `formatError`/`formatFetchError`) — `null` outside the
   *  `"error"` phase. */
  error: string | null;
  /** Re-runs `fetcher` with whatever it would currently read from its own closure (unchanged params,
   *  freshly evaluated) — the shared replacement for every hand-rolled `refresh`/`requestId` pair. */
  reload: () => void;
  /**
   * Overwrites `data` directly, without touching `phase`/`error` or re-running `fetcher`. For the
   * handful of call sites this hook replaces that mutate the *fetched* resource on top of its own
   * fetch effect — an optimistic list removal after a delete succeeds (`BackfillTasks.tsx`'s
   * `handleIngested`), or a mutation endpoint that returns a fresh copy of the whole resource in its
   * own response (`PaperDesk.tsx`'s `applyState`) — rather than this hook trying to model every
   * possible mutation shape itself. Most pages never call this.
   */
  setData: (updater: T | null | ((prev: T | null) => T | null)) => void;
}

export interface UseFetchOptions {
  /** Turns a caught rejection into the display string exposed as `error`. Defaults to
   *  `formatFetchError(err, "Something went wrong.")`, matching the byte-identical `errorMessage`
   *  helper this hook's own call sites used to each keep their own copy of. Most callers should pass
   *  a page-specific fallback via `(err) => formatFetchError(err, t("some.key"))`, or a page's own
   *  richer classifier (`Institutions.tsx`'s `describeFetchError`) when one already exists. */
  formatError?: (err: unknown) => string;
  /**
   * When true, `fetcher` is not called at all and `phase`/`data`/`error` are left exactly as they
   * already are. Matches the `if (!id) return;` guard at the top of many of the hand-rolled effects
   * this hook replaces (`Competition.tsx`'s `leaderboard`/`agentDetail`/`narrative`/`selection`/
   * `findings`, all gated on `selectedRoundId` and/or `selectedAgentId` being non-null) — those
   * effects return before ever calling `setPhase`, so `phase` simply never leaves its initial
   * `"loading"` value until the guard first passes. `skip` reproduces that rather than this hook
   * inventing a 4th "not asked for yet" phase no existing call site had.
   */
  skip?: boolean;
}

/** Turns a caught fetch failure into display text: an `ApiRequestError`'s or `Error`'s own `.message`
 *  when it has one, else `fallback`. Byte-identical to the `errorMessage`/`formatError` helper that
 *  used to be hand-copied into `Competition.tsx`, `GenerationsPanel.tsx`, `TradingAgents.tsx`,
 *  `VibeTrading.tsx`, `BackfillTasks.tsx` and `AgentWorkflow.tsx` (the last two via `describeError` in
 *  `@/api/client`, which this delegates to for parity) — the single copy every one of those files now
 *  imports instead of redeclaring. */
export function formatFetchError(err: unknown, fallback: string): string {
  if (err instanceof ApiRequestError) return err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

/**
 * Fetches `fetcher` on mount and whenever `deps` changes, tracking `phase`/`data`/`error` and
 * guarding against a stale response landing after a newer request already went out or the component
 * unmounted — the same `AbortController`-per-run, cleanup-aborts-it shape `usePortfolio`/
 * `useMacroSnapshot`/`useDecisionTable` already establish, generalised for any resource.
 *
 * `fetcher` is read from a ref on every run rather than placed in the effect's own dependency array,
 * so an inline arrow function (`() => api.thing(id)`) never has to be wrapped in `useCallback` by the
 * caller just to keep this hook from re-fetching every render — only `deps` decides when a new
 * request goes out, exactly like the `[requestId]`/`[selectedRoundId]`-style arrays the effects this
 * hook replaces already keyed on.
 */
export function useFetch<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
  options?: UseFetchOptions,
): UseFetchResult<T> {
  const [phase, setPhase] = useState<FetchPhase>("loading");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped by `reload()` to force the effect below to run again with unchanged `deps`.
  const [generation, setGeneration] = useState(0);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const formatErrorRef = useRef(options?.formatError);
  formatErrorRef.current = options?.formatError;
  const skip = options?.skip ?? false;

  useEffect(() => {
    if (skip) return;
    const controller = new AbortController();
    let cancelled = false;
    setPhase("loading");
    setError(null);
    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (cancelled || controller.signal.aborted) return;
        setData(result);
        setPhase("loaded");
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        const formatError = formatErrorRef.current;
        setError(formatError ? formatError(err) : formatFetchError(err, "Something went wrong."));
        setPhase("error");
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` is the caller's own array; this
    // hook re-runs on it plus `generation`/`skip`, never on `fetcher`/`formatError` themselves (read
    // via ref).
  }, [...deps, generation, skip]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);

  return { phase, data, error, reload, setData };
}

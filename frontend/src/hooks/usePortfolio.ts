/**
 * The current portfolio report: positions, per-account breakdowns and the derived totals.
 *
 * Mirrors the stale-response guard in `useMacroSnapshot`/`useDecisionTable`: an `AbortController` is
 * created per effect run and aborted on cleanup, so a component unmount or an unrelated re-render
 * never leaves an abandoned `/api/portfolio` request running to overwrite fresher state that already
 * landed. `AbortError` is expected on every genuine cancellation and is swallowed rather than
 * surfaced as a failed request, matching the current pattern in `useChartSeries`/`useDecisionTable`/
 * `useMacroSnapshot` rather than the older cancelled-flag one still used in `Tax.tsx`/`Portfolio.tsx`'s
 * store-status effect.
 *
 * A 404 is treated as "no derived positions yet" (`empty`), the same way `Tax.tsx` treats a missing
 * tax report — this is an absence of a build, not a report of zero holdings.
 *
 * **`message` is translated once, at fetch/catch time, not reactively.** It is plain formatted
 * text in component state (`Overview.tsx` also reads it, unchanged, via `PortfolioSection`), not a
 * catalog key a consuming component re-renders through `useT()` -- so if the effect resolves while
 * the page is in English and the reader toggles to Korean afterwards, this one string stays English
 * until the next fetch. Every other string on `Portfolio.tsx` is exempt from that gap because it is
 * translated at render time; this field is the one place in this file's scope that could not be
 * without changing the shape `Overview.tsx` (out of this change's scope) already depends on.
 *
 * **`options.enabled` (default `true`) only ever controls whether the fetch fires.** `/api/portfolio`
 * is one of the owner-only API prefixes (see `@/auth`'s module docstring), and `Overview.tsx` passes
 * `enabled: isOwner` so a member's session never sends that request at all. It deliberately does NOT
 * try to represent "disabled" as one more `phase` -- `phase` stays at its initial `"loading"` for as
 * long as `enabled` is `false`, since it is never resolved either way. `Overview.tsx` does not read
 * this hook's `phase` for a member; it substitutes its own resolved `"empty"` for display, exactly
 * because a stuck-forever `"loading"` is a spinner that never resolves, and this hook has no
 * business inventing a fifth phase just to describe "not applicable to this caller".
 */
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { portfolioApi, type PortfolioReport } from "@/api/portfolio";
import { t } from "@/i18n";

export type Phase = "loading" | "loaded" | "empty" | "error";

export interface PortfolioState {
  report: PortfolioReport | null;
  phase: Phase;
  message: string | null;
  /** Re-runs the fetch. `/api/portfolio` caches nothing (the ledger is replayed on every request --
   *  see its module docstring), so a refresh always reflects the current ledger; it is exposed so
   *  the Overview "Fetch data" button can re-pull this card alongside the ones that do cache. */
  refresh: () => void;
}

export interface UsePortfolioOptions {
  /** See this module's docstring above. Defaults to `true`. */
  enabled?: boolean;
}

export function usePortfolio(options?: UsePortfolioOptions): PortfolioState {
  const enabled = options?.enabled ?? true;
  const [report, setReport] = useState<PortfolioReport | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  // Bumped by `refresh()` to force a re-run of the effect below.
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    portfolioApi
      .report(controller.signal)
      .then((r) => {
        setReport(r);
        setPhase(r.positions.length === 0 ? "empty" : "loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (e instanceof ApiRequestError && e.status === 404) {
          setReport(null);
          setPhase("empty");
          return;
        }
        setMessage(
          e instanceof ApiRequestError
            ? t("portfolio.apiError", { status: e.status, message: e.message })
            : t("portfolio.cannotReachApi"),
        );
        setReport(null);
        setPhase("error");
      });
    return () => {
      controller.abort();
    };
  }, [requestId, enabled]);

  const refresh = useCallback(() => setRequestId((id) => id + 1), []);

  return { report, phase, message, refresh };
}

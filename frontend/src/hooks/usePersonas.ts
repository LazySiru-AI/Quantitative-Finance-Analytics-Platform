/**
 * Fetches the digest cards for the /personas page -- one entry per followed influencer.
 *
 * Deliberately its own hook, fetching `GET /api/personas/cards` only: that endpoint already embeds
 * each card's own `Persona`, so a second request for the bare persona list would just be the same
 * data shape twice. `GET /api/personas/cards` **always answers `200`** (empty array with zero
 * personas, a card with `as_of: null` for a persona with no notes yet) -- there is no "the feature
 * isn't set up" error state to render here, only "loading" while the request is in flight and
 * "error" for a fetch that could not reach the API at all.
 *
 * Shape follows `useTickerNews`: a `Phase` discriminator plus `data`/`message`, an `AbortController`
 * per effect run so a fast unmount or a repeated `reload()` cannot let a stale response overwrite a
 * newer one, and the same "Cannot reach the API. Is uvicorn running on port 8000?" fallback message
 * for a request that never got a response at all. `AbortError` is swallowed rather than surfaced,
 * same reasoning as `useTickerNews`: an aborted fetch is not a failure the reader can act on.
 *
 * `reload()` is exposed (unlike `useTickerNews`, which has no mutating siblings) because
 * `Personas.tsx` needs to refresh the card list after adding/removing a persona or after an ingest
 * job settles -- bumping `reloadToken` re-runs the effect rather than duplicating its fetch logic in
 * a second imperative function.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { personasApi, type DigestCard } from "@/api/personas";
import { t } from "@/i18n";

export type Phase = "loading" | "loaded" | "error";

export interface UsePersonasResult {
  cards: DigestCard[];
  phase: Phase;
  message: string | null;
  /** Re-runs the fetch. Safe to call from a mutation's `.then()` -- e.g. after adding a persona or
   * an ingest job reaching a terminal state. */
  reload: () => void;
}

export function usePersonas(): UsePersonasResult {
  const [cards, setCards] = useState<DigestCard[]>([]);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    personasApi
      .cards(controller.signal)
      .then((res) => {
        setCards(res);
        setPhase("loaded");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setMessage(
          error instanceof ApiRequestError
            ? t("misc.fetch.apiError", { status: error.status, message: error.message })
            : t("misc.fetch.unreachable"),
        );
        setCards([]);
        setPhase("error");
      });
    return () => {
      controller.abort();
    };
  }, [reloadToken]);

  const reload = useCallback(() => setReloadToken((t) => t + 1), []);

  return { cards, phase, message, reload };
}

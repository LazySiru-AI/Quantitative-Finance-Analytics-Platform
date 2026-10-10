/**
 * Fetches the whole macro snapshot in one request, so the rates tile and the movers grid never
 * disagree about what "now" means -- see the module note on `macroApi.snapshot` in `api/macro.ts`.
 *
 * Stale-response guard mirrors `useChartSeries`: an `AbortController` is created per effect run and
 * aborted on cleanup when a dependency changes or the component unmounts, so a `refresh()` fired
 * before the previous fetch resolved does not leave that abandoned request running against the
 * backend's FRED/CNN proxy for a response nothing will read. `macroApi.snapshot` now takes an
 * `AbortSignal` (see `api/macro.ts`) for exactly this. `AbortError` is expected on every genuine
 * cancellation and is swallowed rather than surfaced as a failed request.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { macroApi } from "@/api/macro";
import type { MacroSnapshot } from "@/api/macro";
import { t } from "@/i18n";

export type Phase = "loading" | "loaded" | "error";

export interface MacroSnapshotState {
  snapshot: MacroSnapshot | null;
  phase: Phase;
  message: string | null;
  /** Re-fetches, asking the server to bypass its cache. */
  refresh: () => void;
}

export function useMacroSnapshot(): MacroSnapshotState {
  const [snapshot, setSnapshot] = useState<MacroSnapshot | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  // Bumped by `refresh()`. The first fetch (0) uses the server's cache; every later one forces it.
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    macroApi
      .snapshot(requestId > 0, controller.signal)
      .then((data) => {
        setSnapshot(data);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (e instanceof ApiRequestError) {
          setMessage(t("macro.api.errorStatus", { status: e.status, message: e.message }));
        } else {
          setMessage(t("macro.api.unreachable"));
        }
        setSnapshot(null);
        setPhase("error");
      });
    return () => {
      controller.abort();
    };
  }, [requestId]);

  const refresh = useCallback(() => setRequestId((id) => id + 1), []);

  return { snapshot, phase, message, refresh };
}

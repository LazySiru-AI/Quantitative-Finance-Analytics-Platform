/**
 * Fetches the Macro page's news panel: event-market pricing plus global headlines, in one request.
 *
 * Sibling of `useTickerNews.ts` -- same shape (`phase`/`data`/`message`, an `AbortController` per
 * effect run, `AbortError` swallowed rather than surfaced) for the same reason: this is its own hook
 * rather than folded into `useMacroSnapshot` because the news panel is the slowest thing on the page
 * by an order of magnitude. It fans out across GDELT and Polymarket, both keyless public upstreams --
 * GDELT throttles to roughly one request every five seconds -- and tying that fetch to
 * `useMacroSnapshot`'s single request would hold Fear & Greed, the key indicators and every tile
 * hostage to a headline feed nobody is waiting on to see the numbers.
 *
 * Runs once on mount, unlike `useMacroSnapshot`, which exposes `refresh()`. The macro snapshot's
 * refresh forces the server to bypass its FRED/CNN cache for numbers that move intraday; nothing here
 * needs that same escape hatch yet, and adding an unused control surface is not worth the extra state.
 *
 * **A failed fetch here is a panel-level error, never a page-level one** -- exactly `useTickerNews`'s
 * rule. The backend already guarantees a degraded upstream (dead Polymarket, dead news chain) comes
 * back 200 with an empty section and a warning; reaching this hook's `error` phase at all means the
 * API itself was unreachable, which must still leave the rest of `/macro` on screen.
 */

import { useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { newsApi, type MacroNewsPanel } from "@/api/news";
import type { Phase } from "@/components/MacroNewsPanel";
import { t } from "@/i18n";

export interface MacroNewsState {
  data: MacroNewsPanel | null;
  phase: Phase;
  message: string | null;
}

export function useMacroNews(): MacroNewsState {
  const [data, setData] = useState<MacroNewsPanel | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    newsApi
      .macro(controller.signal)
      .then((panel) => {
        setData(panel);
        setPhase("loaded");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setMessage(
          error instanceof ApiRequestError
            ? t("macro.api.errorStatus", { status: error.status, message: error.message })
            : t("macro.api.unreachable"),
        );
        setData(null);
        setPhase("error");
      });
    return () => {
      controller.abort();
    };
  }, []);

  return { data, phase, message };
}

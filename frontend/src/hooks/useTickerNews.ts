/**
 * Fetches the News & Sentiment panel for one ticker.
 *
 * Deliberately its own hook rather than a section of `useChartSeries` or the ticker summary: the news
 * panel is the slowest thing on the page by an order of magnitude — it fans out across four keyless
 * public upstreams, one of which (GDELT) throttles to roughly one request every five seconds — and
 * folding it into the summary request would hold the chart, the profile and the decision table
 * hostage to a headline feed that nobody is waiting on.
 *
 * Shape follows `useMacroSnapshot`: a `phase` discriminator plus `data`/`message`, an `AbortController`
 * per effect run so a fast symbol change cannot let a stale response overwrite a newer one, and
 * `AbortError` swallowed rather than surfaced as a failure the reader can do nothing about.
 *
 * **A failed fetch here is a panel-level error, never a page-level one.** The backend already
 * guarantees a degraded upstream comes back 200 with an empty section and a warning, so reaching the
 * `error` phase at all means the API itself was unreachable — which must still leave the chart and
 * the decision table on screen. That is why this returns state rather than throwing.
 */

import { useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { newsApi, type TickerNewsPanel } from "@/api/news";
import type { Phase } from "@/components/NewsPanel";
import { t } from "@/i18n";

export interface TickerNewsState {
  data: TickerNewsPanel | null;
  phase: Phase;
  message: string | null;
}

export function useTickerNews(symbol: string | undefined): TickerNewsState {
  const [data, setData] = useState<TickerNewsPanel | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) {
      setData(null);
      setPhase("loading");
      return;
    }
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    newsApi
      .ticker(symbol, controller.signal)
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
  }, [symbol]);

  return { data, phase, message };
}

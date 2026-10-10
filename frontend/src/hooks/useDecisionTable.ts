/**
 * The decision table for one symbol/interval: current rule states plus historical evidence.
 *
 * Mirrors the stale-response guard in `useChartSeries` -- the symbol or interval can change while a
 * request is in flight, and an older response resolving after a newer request has started must never
 * overwrite it. Reuses `describeError` from `useChartSeries` rather than re-deriving the same
 * 404-vs-network-vs-5xx classification a second time. Also mirrors its cleanup: an `AbortController`
 * aborts the in-flight request rather than only discarding its result, so switching intervals does
 * not leave an abandoned request still running against the backend.
 */
import { useEffect, useState } from "react";

import type { Interval } from "@/api/market";
import { rulesApi, type DecisionTable } from "@/api/rules";
import { describeError, type Phase } from "@/hooks/useChartSeries";
import { t } from "@/i18n";

export interface DecisionTableState {
  table: DecisionTable | null;
  phase: Phase;
  message: string | null;
}

export function useDecisionTable(symbol: string, interval: Interval): DecisionTableState {
  const [table, setTable] = useState<DecisionTable | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    rulesApi
      .decisions(symbol, interval, controller.signal)
      .then((result) => {
        setTable(result);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("ticker.decision.notFound", { symbol, interval }));
        setPhase(d.phase);
        setMessage(d.message);
        setTable(null);
      });
    return () => {
      controller.abort();
    };
  }, [symbol, interval]);

  return { table, phase, message };
}

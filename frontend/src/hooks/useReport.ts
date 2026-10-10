/**
 * Hooks for the per-holding report and the strategy backtest, following `useBacktest.ts` exactly.
 *
 * `useReport` is a plain GET keyed on symbol/interval, so it auto-fetches like
 * `useDrawdownProfile` -- a `cancelled`-flag stale-response guard, same `describeError`/`Phase`
 * helpers reused rather than re-derived.
 *
 * `useStrategy` is a POST whose body is arbitrary user input (an entry/exit rule, holding and stop
 * parameters), so nothing fires until the caller submits one via the returned `run`. Same reasoning
 * as `useEventStudy`: a `cancelled` flag alone is not enough because a user can submit a second,
 * different request before the first resolves, and effect-scoped cleanup never runs between two
 * calls to the same `run`. Each `run` opens an `AbortController`, stores it in a ref, and aborts +
 * replaces it on the next call; a response is only applied if its controller is still the one in the
 * ref, so a slow older request can never clobber a faster newer one.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { reportApi, type Interval, type Report, type StrategyRequest, type StrategyResult } from "@/api/report";
import { t } from "@/i18n";
import { describeError, type Phase } from "@/hooks/useChartSeries";

// --- report: auto-fetch on symbol/interval -----------------------------------

export interface ReportState {
  report: Report | null;
  phase: Phase;
  message: string | null;
}

export function useReport(symbol: string, interval: Interval): ReportState {
  const [report, setReport] = useState<Report | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setMessage(null);
    reportApi
      .get(symbol, interval)
      .then((result) => {
        if (cancelled) return;
        setReport(result);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const d = describeError(e, t("market.report.noReport", { symbol, interval }));
        setPhase(d.phase);
        setMessage(d.message);
        setReport(null);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, interval]);

  return { report, phase, message };
}

// --- strategy: on-demand, an arbitrary strategy spec --------------------------

export interface StrategyRunState {
  result: StrategyResult | null;
  phase: Phase;
  message: string | null;
  run: (request: StrategyRequest) => void;
}

export function useStrategy(): StrategyRunState {
  const [result, setResult] = useState<StrategyResult | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback((request: StrategyRequest) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    setMessage(null);
    reportApi
      .strategy(request, controller.signal)
      .then((response) => {
        if (controllerRef.current !== controller) return;
        setResult(response);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (controllerRef.current !== controller) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("market.report.noStrategyResult", { symbol: request.symbol }));
        setPhase(d.phase);
        setMessage(d.message);
        setResult(null);
      });
  }, []);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { result, phase, message, run };
}

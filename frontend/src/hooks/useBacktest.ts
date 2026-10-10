/**
 * Hooks for the backtest workbench.
 *
 * `drawdowns` is a plain GET keyed on symbol/interval/basis, so it auto-fetches exactly like
 * `useDecisionTable` -- same `cancelled`-flag stale-response guard, same `describeError`/`Phase`
 * helpers from `useChartSeries`, reused rather than re-derived.
 *
 * `event-study`, `reverse` and `scan` are POSTs whose body is arbitrary user input (condition
 * expressions, indicator specs, a list of scan expressions), so nothing fires until the caller
 * submits one via the returned `run`. A `cancelled` flag alone is not enough there: a user can
 * submit a second, different request before the first resolves, and effect-scoped cleanup never
 * runs between two calls to the same `run`. Each `run` instead opens an `AbortController`, stores it
 * in a ref, and aborts + replaces it on the next call; a response is only applied if its controller
 * is still the one in the ref, so a slow older request can never clobber a faster newer one.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { Interval } from "@/api/market";
import {
  backtestApi,
  type DrawdownBasis,
  type DrawdownProfile,
  type EventStudy,
  type EventStudyRequest,
  type ReverseConditioning,
  type ReverseRequest,
  type ScanRequest,
  type ScanResult,
} from "@/api/backtest";
import { describeError, type Phase } from "@/hooks/useChartSeries";
import { t } from "@/i18n";

export const DEFAULT_TOP_EPISODES = 10;

// --- drawdown profile: auto-fetch on symbol/interval/basis -------------------

export interface DrawdownProfileState {
  profile: DrawdownProfile | null;
  phase: Phase;
  message: string | null;
}

export function useDrawdownProfile(
  symbol: string,
  interval: Interval,
  basis: DrawdownBasis,
  top: number = DEFAULT_TOP_EPISODES,
): DrawdownProfileState {
  const [profile, setProfile] = useState<DrawdownProfile | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setMessage(null);
    backtestApi
      .drawdowns(symbol, { interval, basis, top })
      .then((result) => {
        if (cancelled) return;
        setProfile(result);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const d = describeError(e, t("strategy.backtest.error.noDrawdownProfile", { symbol, interval }));
        setPhase(d.phase);
        setMessage(d.message);
        setProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, interval, basis, top]);

  return { profile, phase, message };
}

// --- event study: on-demand, one or two condition arms -----------------------

export interface EventStudyRunState {
  study: EventStudy | null;
  phase: Phase;
  message: string | null;
  run: (request: EventStudyRequest) => void;
}

export function useEventStudy(): EventStudyRunState {
  const [study, setStudy] = useState<EventStudy | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback((request: EventStudyRequest) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    setMessage(null);
    backtestApi
      .eventStudy(request, controller.signal)
      .then((result) => {
        if (controllerRef.current !== controller) return;
        setStudy(result);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (controllerRef.current !== controller) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("strategy.backtest.error.noEventStudyResult", { symbol: request.symbol }));
        setPhase(d.phase);
        setMessage(d.message);
        setStudy(null);
      });
  }, []);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { study, phase, message, run };
}

// --- reverse conditioning: on-demand, but the caller typically fires it right
//     away with the default request so the section still reads as "loaded for
//     this symbol" rather than requiring a second, redundant user action -------

export interface ReverseConditioningRunState {
  reverse: ReverseConditioning | null;
  phase: Phase;
  message: string | null;
  run: (request: ReverseRequest) => void;
}

export function useReverseConditioning(): ReverseConditioningRunState {
  const [reverse, setReverse] = useState<ReverseConditioning | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback((request: ReverseRequest) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    setMessage(null);
    backtestApi
      .reverse(request, controller.signal)
      .then((result) => {
        if (controllerRef.current !== controller) return;
        setReverse(result);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (controllerRef.current !== controller) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(
          e,
          t("strategy.backtest.error.noReverseProfile", { symbol: request.symbol }),
        );
        setPhase(d.phase);
        setMessage(d.message);
        setReverse(null);
      });
  }, []);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { reverse, phase, message, run };
}

// --- scan: on-demand, an arbitrary list of expressions ------------------------

export interface ScanRunState {
  scan: ScanResult | null;
  phase: Phase;
  message: string | null;
  run: (request: ScanRequest) => void;
}

export function useScan(): ScanRunState {
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback((request: ScanRequest) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    setMessage(null);
    backtestApi
      .scan(request, controller.signal)
      .then((result) => {
        if (controllerRef.current !== controller) return;
        setScan(result);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (controllerRef.current !== controller) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("strategy.backtest.error.noScanResult", { symbol: request.symbol }));
        setPhase(d.phase);
        setMessage(d.message);
        setScan(null);
      });
  }, []);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { scan, phase, message, run };
}

/**
 * Hooks for the thesis loop page.
 *
 * `useThesisLedger` is a plain GET keyed on symbol, auto-fetching like `useReport` and
 * `useDrawdownProfile` -- same `cancelled`-flag stale-response guard, same `describeError`/`Phase`
 * helpers from `useChartSeries`. It loads before any run happens and stays loaded whether or not one
 * ever does, because two of the four guards in `app/thesis/__init__.py` apply regardless: the ledger
 * is the trial denominator (guard 2) and a burned holdout is loud (guard 3) whether this session
 * caused it or an earlier one did. It exposes `refresh` because a run changes both -- a new record
 * lands in the ledger and the holdout may move from unused to spent or spent to burned -- and the
 * page needs to show that without a full reload.
 *
 * `useThesisRun` is a POST whose body is a symbol/interval/budget triple the user chooses, so
 * nothing fires until `run` is called. Same `AbortController`-in-a-ref pattern as `useStrategy` and
 * `useScan` in `useBacktest.ts`/`useReport.ts`: a second submission aborts and replaces the first
 * rather than letting a slow older response clobber a faster newer one.
 *
 * **Contract note.** `@/api/thesis` is being written by another agent in parallel with this file and
 * did not exist yet when this was written. The shape assumed here mirrors
 * `backend/app/thesis/models.py` field for field, following the convention every other `api/*.ts`
 * module in this repo already uses (snake_case fields, no renaming). Expected surface:
 *   - types: `Direction`, `ThesisStatus`, `Verdict`, `HoldoutStatus`, `LoopOutcome`, `Thesis`,
 *     `Evidence`, `HoldoutState`, `LedgerStats`, `ThesisRecord`, `RegimeSlice`, `TaxImpact`,
 *     `StrategyCard`, `LoopResult` -- reusing `Distribution` from `@/api/backtest`, `StrategyResult`
 *     and `FactBundle` from `@/api/report`, and `MarketWarning`/`Interval` from `@/api/market`,
 *     exactly as `models.py` imports them rather than redefining them.
 *   - `thesisApi.ledger(symbol, signal?)` -> `Promise<{ symbol; stats: LedgerStats; records:
 *     ThesisRecord[]; holdout: HoldoutState | null }>` -- every thesis ever registered for the
 *     ticker plus its holdout state, in one call, so the ledger and holdout sections can render
 *     before any run.
 *   - `thesisApi.run({ symbol, interval?, budget? }, signal?)` -> `Promise<LoopResult>`.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { Interval } from "@/api/market";
import { thesisApi, type HoldoutState, type LedgerStats, type LoopResult, type ThesisRecord } from "@/api/thesis";
import { describeError, type Phase } from "@/hooks/useChartSeries";
import { t } from "@/i18n";

// --- ledger + holdout: auto-fetch on symbol, refreshable after a run --------

export interface ThesisLedgerState {
  stats: LedgerStats | null;
  records: ThesisRecord[];
  holdout: HoldoutState | null;
  phase: Phase;
  message: string | null;
  refresh: () => void;
}

const NO_RECORDS: ThesisRecord[] = [];

export function useThesisLedger(symbol: string): ThesisLedgerState {
  const [stats, setStats] = useState<LedgerStats | null>(null);
  const [records, setRecords] = useState<ThesisRecord[]>(NO_RECORDS);
  const [holdout, setHoldout] = useState<HoldoutState | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setMessage(null);
    // Both in one shot. The trial count and the holdout state are two halves of "what has already
    // been spent on this ticker", and fetching them independently would let a stale holdout render
    // beside a fresh ledger -- which is exactly the pair a reader must be able to trust together.
    Promise.all([thesisApi.ledger(symbol), thesisApi.holdout(symbol)])
      .then(([ledgerBody, holdoutBody]) => {
        if (cancelled) return;
        setStats(ledgerBody.stats);
        setRecords(ledgerBody.records);
        setHoldout(holdoutBody.state);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const d = describeError(e, t("strategy.thesis.error.noLedger", { symbol }));
        setPhase(d.phase);
        setMessage(d.message);
        setStats(null);
        setRecords(NO_RECORDS);
        setHoldout(null);
      });
    return () => {
      cancelled = true;
    };
    // `version` is a manual refresh trigger, not a value read in the body.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return { stats, records, holdout, phase, message, refresh };
}

// --- run: on-demand, symbol + interval + budget -----------------------------

export interface ThesisRunState {
  result: LoopResult | null;
  phase: Phase;
  message: string | null;
  run: (request: { symbol: string; interval?: Interval; budget?: number }) => void;
  reset: () => void;
}

export function useThesisRun(): ThesisRunState {
  const [result, setResult] = useState<LoopResult | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback((request: { symbol: string; interval?: Interval; budget?: number }) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("loading");
    setMessage(null);
    thesisApi
      .run(request, controller.signal)
      .then((response: LoopResult) => {
        if (controllerRef.current !== controller) return;
        setResult(response);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (controllerRef.current !== controller) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("strategy.thesis.error.noRunResult", { symbol: request.symbol }));
        setPhase(d.phase);
        setMessage(d.message);
        setResult(null);
      });
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    setResult(null);
    setPhase("idle");
    setMessage(null);
  }, []);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { result, phase, message, run, reset };
}

// --- holdout description -----------------------------------------------------

/**
 * Mirrors `app.thesis.holdout.describe` (`backend/app/thesis/holdout.py`) verbatim, sentence for
 * sentence, so the text a user reads about a burned holdout is the same text the backend would
 * print rather than a paraphrase that can silently drift from it. Computed client-side from
 * `HoldoutState` rather than trusting a duplicate string over the wire, since that keeps this
 * component correct even if the eventual `@/api/thesis` payload does not carry a pre-rendered
 * sentence.
 */
export function describeHoldout(state: HoldoutState | null): string {
  if (state === null) return t("strategy.thesis.holdout.none");
  switch (state.status) {
    case "unused":
      return t("strategy.thesis.holdout.unused", { date: state.split_date });
    case "spent": {
      const when = state.evaluated_at
        ? state.evaluated_at.slice(0, 10)
        : t("strategy.thesis.holdout.earlierRun");
      return t("strategy.thesis.holdout.spent", { date: state.split_date, when });
    }
    case "burned":
      return t("strategy.thesis.holdout.burned", {
        date: state.split_date,
        attempts: state.attempts,
      });
    default:
      return "";
  }
}

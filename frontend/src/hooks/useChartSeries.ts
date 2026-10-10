/**
 * Bars plus indicator series for one symbol at one interval.
 *
 * Extracted so the single chart and the four-timeframe grid share one implementation. They are the
 * same request against different intervals, and duplicating the fetch logic would let the two views
 * drift — the grid quietly omitting a warning the single view shows, or handling a 404 differently.
 *
 * Both effects below abort their in-flight request on cleanup, via an `AbortController` passed as
 * `marketApi.bars`/`indicators`'s `signal` option, rather than only flipping a `cancelled` flag and
 * letting the request complete anyway. The four-timeframe grid mounts all four intervals at once and
 * a user clicking through tabs fires a new request on every click; without a real abort, each
 * abandoned request still runs to completion against the backend's Yahoo/FRED proxy, burning real
 * upstream quota for a response nothing will ever read. `AbortError` is expected on every genuine
 * cancellation and is swallowed rather than surfaced as a failed request, matching how
 * `useBacktest.ts`/`useReport.ts`/`useThesis.ts` treat it for their `run`-style requests.
 */

import { useEffect, useMemo, useState } from "react";

import { ApiRequestError } from "@/api/client";
import {
  marketApi,
  type Bar,
  type BarSource,
  type IndicatorSeries,
  type Interval,
  type MarketWarning,
} from "@/api/market";
import { colorsByKey, overlaysFor, type Overlay } from "@/components/overlays";
import { t } from "@/i18n";

export type Phase = "idle" | "loading" | "loaded" | "error" | "notfound";

export function describeError(
  e: unknown,
  notFoundMessage: string,
): { phase: Phase; message: string } {
  if (e instanceof ApiRequestError) {
    if (e.status === 404) return { phase: "notfound", message: notFoundMessage };
    return { phase: "error", message: t("ticker.error.apiStatus", { status: e.status, message: e.message }) };
  }
  return { phase: "error", message: t("ticker.error.unreachable") };
}

export interface ChartSeriesState {
  bars: Bar[];
  /** The interval `bars` were fetched with; `null` before the first load. */
  barsInterval: Interval | null;
  source: BarSource | null;
  ts: string[];
  /** The interval `ts`/`series` were fetched with; `null` before the first indicators load. Compare
   *  against `barsInterval` before pairing `ts`/`series` with `bars` in a `Chart` -- see this field's
   *  declaration on the hook body above for why the two can disagree for a render or two. */
  tsInterval: Interval | null;
  series: IndicatorSeries[];
  /** Series key -> overlay colour, so the chart never has to invent one. */
  colors: Record<string, string>;
  warnings: MarketWarning[];
  barsPhase: Phase;
  barsMessage: string | null;
  indicatorsPhase: Phase;
  indicatorsMessage: string | null;
}

const NO_BARS: Bar[] = [];
const NO_SERIES: IndicatorSeries[] = [];
const NO_TS: string[] = [];
const NO_WARNINGS: MarketWarning[] = [];

export function useChartSeries(
  symbol: string,
  interval: Interval,
  overlays: Overlay[],
): ChartSeriesState {
  const [bars, setBars] = useState<Bar[]>(NO_BARS);
  /** The interval `bars` were fetched with -- **not** the `interval` argument.
   *
   * The two differ for exactly one render on every interval change: React re-renders with the new
   * `interval` before this hook's fetch effect has run, so a consumer pairing the argument with
   * `bars` gets the previous interval's bars labelled as the new one. `Chart.toTime` renders a
   * daily bar as a `"YYYY-MM-DD"` business-day string, so 4h bars labelled `1d` collapse to
   * duplicate dates and lightweight-charts throws "data must be asc ordered by time". `barsPhase`
   * cannot guard it, because that is set inside the same effect that has not run yet.
   *
   * `null` until the first successful load, and left at its previous value while a new interval is
   * in flight so the chart keeps drawing the old interval correctly rather than tearing. */
  const [barsInterval, setBarsInterval] = useState<Interval | null>(null);
  const [source, setSource] = useState<BarSource | null>(null);
  const [barWarnings, setBarWarnings] = useState<MarketWarning[]>(NO_WARNINGS);
  const [barsPhase, setBarsPhase] = useState<Phase>("loading");
  const [barsMessage, setBarsMessage] = useState<string | null>(null);

  const [ts, setTs] = useState<string[]>(NO_TS);
  /** The interval `ts`/`series` were fetched with -- the same pairing trick as `barsInterval` above,
   *  and for the identical reason. This effect has no `barsPhase` guard of its own: it fires on the
   *  same `[symbol, interval, ...]` change as the bars effect, but the two requests race, and
   *  indicators resolving first would otherwise hand the page a fresh `ts`/`series` still labelled
   *  with the *previous* render's `interval` implicitly -- exactly the "4h data captioned 1d" shape
   *  that made `Chart.tsx`'s `buildLinePoints` collapse intraday ISO timestamps into duplicate
   *  business-day strings and throw. Consumers must compare this against `barsInterval` before
   *  passing `ts`/`series` to `Chart` -- see `Ticker.tsx`. */
  const [tsInterval, setTsInterval] = useState<Interval | null>(null);
  const [series, setSeries] = useState<IndicatorSeries[]>(NO_SERIES);
  const [colors, setColors] = useState<Record<string, string>>({});
  const [indicatorWarnings, setIndicatorWarnings] = useState<MarketWarning[]>(NO_WARNINGS);
  const [indicatorsPhase, setIndicatorsPhase] = useState<Phase>("idle");
  const [indicatorsMessage, setIndicatorsMessage] = useState<string | null>(null);

  // Only the overlays this interval can compute. Anchored VWAP is undefined on daily bars, and
  // sending it anyway is a 400 that would blank the whole panel rather than one line.
  const applicable = useMemo(() => overlaysFor(overlays, interval), [overlays, interval]);
  const specs = useMemo(() => applicable.map((o) => o.spec), [applicable]);
  const specsKey = specs.join("|");
  const colorKey = applicable.map((o) => o.color).join("|");

  useEffect(() => {
    const controller = new AbortController();
    setBarsPhase("loading");
    setBarsMessage(null);
    marketApi
      .bars(symbol, interval, { signal: controller.signal })
      .then((result) => {
        setBars(result.bars);
        // Set together with `bars`, in the same commit, so the pair can never disagree.
        setBarsInterval(interval);
        setSource(result.source);
        setBarWarnings(result.warnings);
        setBarsPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("ticker.chart.barsNotFound", { interval, symbol }));
        setBarsPhase(d.phase);
        setBarsMessage(d.message);
        setBars(NO_BARS);
        setBarsInterval(null);
        setBarWarnings(NO_WARNINGS);
      });
    return () => {
      controller.abort();
    };
  }, [symbol, interval]);

  useEffect(() => {
    if (specs.length === 0) {
      setSeries(NO_SERIES);
      setTs(NO_TS);
      setTsInterval(null);
      setColors({});
      setIndicatorWarnings(NO_WARNINGS);
      setIndicatorsPhase("idle");
      setIndicatorsMessage(null);
      return;
    }
    const controller = new AbortController();
    setIndicatorsPhase("loading");
    setIndicatorsMessage(null);
    marketApi
      .indicators(symbol, interval, specs, { signal: controller.signal })
      .then((response) => {
        setSeries(response.series);
        setTs(response.ts);
        // Set together with `ts`/`series`, in the same commit, mirroring `barsInterval` above -- so
        // a consumer reading `tsInterval` alongside `ts` never sees the pair mismatched against the
        // `interval` argument for even one render.
        setTsInterval(interval);
        setColors(colorsByKey(applicable, response.series.map((s) => s.key)));
        setIndicatorWarnings(response.warnings);
        setIndicatorsPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        const d = describeError(e, t("ticker.chart.indicatorsNotFound", { symbol }));
        setIndicatorsPhase(d.phase);
        setIndicatorsMessage(d.message);
        setSeries(NO_SERIES);
        setTsInterval(null);
      });
    return () => {
      controller.abort();
    };
    // `specsKey` and `colorKey` are the stable dependencies; `specs` and `applicable` are arrays
    // rebuilt every render, and depending on them directly would refetch on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, interval, specsKey, colorKey]);

  const warnings = useMemo(
    () => [...barWarnings, ...indicatorWarnings],
    [barWarnings, indicatorWarnings],
  );

  return {
    bars,
    barsInterval,
    source,
    ts,
    tsInterval,
    series,
    colors,
    warnings,
    barsPhase,
    barsMessage,
    indicatorsPhase,
    indicatorsMessage,
  };
}
